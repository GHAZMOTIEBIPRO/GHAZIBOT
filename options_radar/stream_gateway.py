from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _symbols(raw: str, maximum: int) -> list[str]:
    output: list[str] = []
    for token in str(raw or "").replace("\n", ",").split(","):
        symbol = token.strip().upper().replace(" ", "")
        if symbol and symbol not in output:
            output.append(symbol)
        if len(output) >= maximum:
            break
    return output


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if hasattr(value, "model_dump"):
        try:
            return _plain(value.model_dump())
        except Exception:
            pass
    if hasattr(value, "dict"):
        try:
            return _plain(value.dict())
        except Exception:
            pass
    return value


def _event_time(row: dict[str, Any]) -> datetime | None:
    for key in ("t", "timestamp", "time"):
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, datetime):
            return (
                value.replace(tzinfo=timezone.utc)
                if value.tzinfo is None
                else value.astimezone(timezone.utc)
            )
        text = str(value).strip()
        if not text:
            continue
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        return (
            parsed.replace(tzinfo=timezone.utc)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone.utc)
        )
    return None


def watchdog_restart_reason(
    *,
    market_active: bool,
    connected_age_seconds: float | None,
    event_age_seconds: float | None,
    grace_seconds: float,
    stale_seconds: float,
) -> str | None:
    """Return a transport-health restart reason, never a trading signal.

    A socket is only considered stale while the configured market window is
    active and after a connection grace period. This prevents overnight and
    holiday reconnect storms while still detecting a silently hung data stream.
    """
    if not market_active or connected_age_seconds is None:
        return None
    if connected_age_seconds < max(1.0, grace_seconds):
        return None
    if event_age_seconds is None:
        return "no_events_after_connect_grace"
    if event_age_seconds > max(1.0, stale_seconds):
        return f"stream_event_stale_{event_age_seconds:.1f}s"
    return None


@dataclass
class SnapshotStore:
    path: Path
    stock_feed: str
    option_feed: str
    flush_interval_seconds: float = 0.75
    gap_warn_seconds: float = 5.0
    lock: threading.RLock = field(default_factory=threading.RLock)
    last_flush_monotonic: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)
    _last_event_monotonic: dict[str, float] = field(default_factory=dict)
    _connected_monotonic: dict[str, float] = field(default_factory=dict)
    _events_since_connect: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.payload = {
            "schema_version": 2,
            "source": "alpaca_stream_gateway",
            "generated_at": _now(),
            "stock_feed": self.stock_feed,
            "option_feed": self.option_feed,
            "stocks": {},
            "options": {},
            "health": {
                "started_at": _now(),
                "last_event_at": None,
                "stock_events": 0,
                "option_events": 0,
                "streams": {
                    "stock": self._stream_health_template(),
                    "options": self._stream_health_template(),
                },
            },
        }

    @staticmethod
    def _stream_health_template() -> dict[str, Any]:
        return {
            "status": "idle",
            "detail": "",
            "connected_at": None,
            "last_event_at": None,
            "last_source_event_at": None,
            "events": 0,
            "event_lag_ms": None,
            "max_event_lag_ms": 0,
            "last_transport_gap_seconds": None,
            "max_transport_gap_seconds": 0.0,
            "gaps_over_warn": 0,
            "reconnect_attempts": 0,
            "watchdog_restarts": 0,
        }

    def _stream_health(self, kind: str) -> dict[str, Any]:
        health = self.payload.setdefault("health", {})
        streams = health.setdefault("streams", {})
        return streams.setdefault(kind, self._stream_health_template())

    def mark_connecting(self, kind: str) -> None:
        now = _now()
        with self.lock:
            self._connected_monotonic[kind] = time.monotonic()
            self._last_event_monotonic.pop(kind, None)
            self._events_since_connect[kind] = 0
            row = self._stream_health(kind)
            row["status"] = "connecting"
            row["detail"] = ""
            row["connected_at"] = now
            self.payload["health"]["heartbeat_at"] = now
            self.payload["generated_at"] = now
        self.flush(force=True)

    def update(self, asset: str, event: Any) -> None:
        row = _plain(event)
        if not isinstance(row, dict):
            return
        symbol = str(row.get("S") or row.get("symbol") or "").upper().replace(" ", "")
        if not symbol:
            return
        event_type = str(row.get("T") or row.get("type") or "event").lower()
        now_dt = datetime.now(timezone.utc)
        now_text = now_dt.isoformat()
        now_mono = time.monotonic()
        source_time = _event_time(row)
        source_lag_ms = None
        if source_time is not None:
            source_lag_ms = max(0, round((now_dt - source_time).total_seconds() * 1000))

        with self.lock:
            bucket = self.payload["stocks"] if asset == "stock" else self.payload["options"]
            record = bucket.setdefault(symbol, {})
            record[event_type] = row
            record["last_event_at"] = now_text

            health_key = "stock_events" if asset == "stock" else "option_events"
            self.payload["health"][health_key] = int(
                self.payload["health"].get(health_key, 0)
            ) + 1
            self.payload["health"]["last_event_at"] = now_text

            stream_health = self._stream_health(asset)
            previous_mono = self._last_event_monotonic.get(asset)
            if previous_mono is not None:
                gap = max(0.0, now_mono - previous_mono)
                stream_health["last_transport_gap_seconds"] = round(gap, 3)
                stream_health["max_transport_gap_seconds"] = round(
                    max(float(stream_health.get("max_transport_gap_seconds") or 0.0), gap),
                    3,
                )
                if gap >= max(0.1, float(self.gap_warn_seconds)):
                    stream_health["gaps_over_warn"] = int(
                        stream_health.get("gaps_over_warn", 0)
                    ) + 1
            self._last_event_monotonic[asset] = now_mono
            self._events_since_connect[asset] = int(
                self._events_since_connect.get(asset, 0)
            ) + 1

            stream_health["status"] = "receiving"
            stream_health["last_event_at"] = now_text
            stream_health["events"] = int(stream_health.get("events", 0)) + 1
            if source_time is not None:
                stream_health["last_source_event_at"] = source_time.isoformat()
            if source_lag_ms is not None:
                stream_health["event_lag_ms"] = source_lag_ms
                stream_health["max_event_lag_ms"] = max(
                    int(stream_health.get("max_event_lag_ms") or 0),
                    source_lag_ms,
                )
            self.payload["generated_at"] = now_text
        self.flush_if_due()

    def heartbeat(self, status: str, detail: str = "", *, kind: str | None = None) -> None:
        now = _now()
        with self.lock:
            health = self.payload.setdefault("health", {})
            health["heartbeat_at"] = now
            if kind:
                row = self._stream_health(kind)
                row["status"] = status
                row["detail"] = detail[:500]
            else:
                health["status"] = status
                health["detail"] = detail[:500]
            self.payload["generated_at"] = now
        self.flush(force=True)

    def record_reconnect(self, kind: str, detail: str, *, watchdog: bool = False) -> None:
        with self.lock:
            row = self._stream_health(kind)
            if watchdog:
                row["watchdog_restarts"] = int(row.get("watchdog_restarts", 0)) + 1
            else:
                row["reconnect_attempts"] = int(row.get("reconnect_attempts", 0)) + 1
            row["detail"] = detail[:500]
            row["status"] = "watchdog_restart" if watchdog else "reconnecting"
            self.payload["generated_at"] = _now()
        self.flush(force=True)

    def connected_age_seconds(self, kind: str) -> float | None:
        with self.lock:
            started = self._connected_monotonic.get(kind)
        if started is None:
            return None
        return max(0.0, time.monotonic() - started)

    def event_age_seconds(self, kind: str) -> float | None:
        with self.lock:
            last = self._last_event_monotonic.get(kind)
        if last is None:
            return None
        return max(0.0, time.monotonic() - last)

    def events_since_connect(self, kind: str) -> int:
        with self.lock:
            return int(self._events_since_connect.get(kind, 0))

    def flush_if_due(self) -> None:
        if time.monotonic() - self.last_flush_monotonic >= self.flush_interval_seconds:
            self.flush()

    def flush(self, force: bool = False) -> None:
        with self.lock:
            if (
                not force
                and time.monotonic() - self.last_flush_monotonic
                < self.flush_interval_seconds
            ):
                return
            snapshot = json.loads(json.dumps(self.payload, default=str))
            self.last_flush_monotonic = time.monotonic()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _market_active_for_watchdog(kind: str) -> bool:
    try:
        from options_radar.market_clock import market_clock_state

        state = market_clock_state()
        session_mode = str(os.getenv("STREAM_WATCHDOG_SESSION", "regular") or "regular").lower()
        if session_mode == "extended" and kind == "stock":
            return bool(state.is_extended_activity_open)
        return bool(state.is_regular_open)
    except Exception:
        # Fail closed: inability to establish a valid market window must never
        # create a reconnect storm.
        return False


def run_alpaca_gateway(
    *,
    stock_symbols: list[str],
    option_contracts: list[str],
    snapshot_path: str | Path,
    run_seconds: int = 0,
) -> None:
    """Run resilient Alpaca stock and option streams in parallel.

    Free IEX/indicative feeds remain context-grade. If SIP/OPRA entitlements are
    added later, feed environment variables change without changing the snapshot
    schema. The watchdog is transport telemetry only; it cannot create or promote
    a trading signal.
    """
    try:
        from alpaca.data.enums import DataFeed, OptionsFeed
        from alpaca.data.live import OptionDataStream, StockDataStream
    except ImportError as exc:
        raise RuntimeError(
            "Streaming dependencies are not installed. Use requirements-stream.txt"
        ) from exc

    api_key = str(os.getenv("ALPACA_API_KEY") or "").strip()
    secret_key = str(os.getenv("ALPACA_SECRET_KEY") or "").strip()
    if not api_key or not secret_key:
        raise RuntimeError(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY are required for streaming"
        )

    stock_feed_name = str(os.getenv("ALPACA_STOCK_FEED", "iex") or "iex").lower()
    option_feed_name = str(
        os.getenv("ALPACA_OPTIONS_FEED", "indicative") or "indicative"
    ).lower()
    stock_feed = DataFeed.SIP if stock_feed_name == "sip" else DataFeed.IEX
    option_feed = (
        OptionsFeed.OPRA if option_feed_name == "opra" else OptionsFeed.INDICATIVE
    )

    gap_warn = max(0.5, float(os.getenv("STREAM_GAP_WARN_SECONDS", "5")))
    store = SnapshotStore(
        Path(snapshot_path),
        stock_feed_name,
        option_feed_name,
        gap_warn_seconds=gap_warn,
    )
    stop_event = threading.Event()
    stream_lock = threading.Lock()
    active_streams: dict[str, Any] = {}

    def set_stream(kind: str, stream: Any | None) -> None:
        with stream_lock:
            if stream is None:
                active_streams.pop(kind, None)
            else:
                active_streams[kind] = stream

    async def stock_quote(event: Any) -> None:
        store.update("stock", event)

    async def stock_trade(event: Any) -> None:
        store.update("stock", event)

    async def option_quote(event: Any) -> None:
        store.update("options", event)

    async def option_trade(event: Any) -> None:
        store.update("options", event)

    def run_stock() -> None:
        backoff = 1.0
        while not stop_event.is_set() and stock_symbols:
            stream = StockDataStream(
                api_key,
                secret_key,
                raw_data=True,
                feed=stock_feed,
            )
            set_stream("stock", stream)
            store.mark_connecting("stock")
            stream.subscribe_quotes(stock_quote, *stock_symbols)
            stream.subscribe_trades(stock_trade, *stock_symbols)
            try:
                stream.run()
                if stop_event.is_set():
                    break
                if store.events_since_connect("stock") > 0:
                    backoff = 1.0
                store.record_reconnect("stock", "stream ended without error")
                if stop_event.wait(backoff):
                    break
                backoff = min(30.0, backoff * 2.0)
            except Exception as exc:
                if store.events_since_connect("stock") > 0:
                    backoff = 1.0
                store.record_reconnect(
                    "stock",
                    f"{type(exc).__name__}: {exc}",
                )
                if stop_event.wait(backoff):
                    break
                backoff = min(30.0, backoff * 2.0)
            finally:
                set_stream("stock", None)

    def run_options() -> None:
        backoff = 1.0
        while not stop_event.is_set() and option_contracts:
            stream = OptionDataStream(
                api_key,
                secret_key,
                raw_data=True,
                feed=option_feed,
            )
            set_stream("options", stream)
            store.mark_connecting("options")
            stream.subscribe_quotes(option_quote, *option_contracts)
            stream.subscribe_trades(option_trade, *option_contracts)
            try:
                stream.run()
                if stop_event.is_set():
                    break
                if store.events_since_connect("options") > 0:
                    backoff = 1.0
                store.record_reconnect("options", "stream ended without error")
                if stop_event.wait(backoff):
                    break
                backoff = min(30.0, backoff * 2.0)
            except Exception as exc:
                if store.events_since_connect("options") > 0:
                    backoff = 1.0
                store.record_reconnect(
                    "options",
                    f"{type(exc).__name__}: {exc}",
                )
                if stop_event.wait(backoff):
                    break
                backoff = min(30.0, backoff * 2.0)
            finally:
                set_stream("options", None)

    threads: list[threading.Thread] = []
    if stock_symbols:
        threads.append(
            threading.Thread(
                target=run_stock,
                name="alpaca-stock-stream",
                daemon=True,
            )
        )
    if option_contracts:
        threads.append(
            threading.Thread(
                target=run_options,
                name="alpaca-option-stream",
                daemon=True,
            )
        )
    if not threads:
        raise RuntimeError(
            "No stock symbols or option contracts were configured for streaming"
        )

    watchdog_enabled = str(
        os.getenv("STREAM_WATCHDOG_ENABLED", "true") or "true"
    ).strip().lower() in {"1", "true", "yes", "on"}
    watchdog_stale = max(10.0, float(os.getenv("STREAM_WATCHDOG_STALE_SECONDS", "45")))
    watchdog_grace = max(10.0, float(os.getenv("STREAM_WATCHDOG_GRACE_SECONDS", "60")))
    watchdog_interval = max(2.0, float(os.getenv("STREAM_WATCHDOG_INTERVAL_SECONDS", "5")))

    def run_watchdog() -> None:
        while not stop_event.wait(watchdog_interval):
            if not watchdog_enabled:
                continue
            with stream_lock:
                streams = dict(active_streams)
            for kind, stream in streams.items():
                reason = watchdog_restart_reason(
                    market_active=_market_active_for_watchdog(kind),
                    connected_age_seconds=store.connected_age_seconds(kind),
                    event_age_seconds=store.event_age_seconds(kind),
                    grace_seconds=watchdog_grace,
                    stale_seconds=watchdog_stale,
                )
                if not reason:
                    continue
                store.record_reconnect(kind, reason, watchdog=True)
                try:
                    stream.stop()
                except Exception as exc:
                    store.heartbeat(
                        "watchdog_stop_failed",
                        f"{type(exc).__name__}: {exc}",
                        kind=kind,
                    )

    for thread in threads:
        thread.start()
    watchdog_thread = threading.Thread(
        target=run_watchdog,
        name="alpaca-stream-watchdog",
        daemon=True,
    )
    watchdog_thread.start()
    store.heartbeat(
        "running",
        f"stocks={len(stock_symbols)} options={len(option_contracts)} watchdog={watchdog_enabled}",
    )

    try:
        if run_seconds > 0:
            stop_event.wait(run_seconds)
        else:
            while not stop_event.wait(5.0):
                store.heartbeat(
                    "running",
                    f"stocks={len(stock_symbols)} options={len(option_contracts)} watchdog={watchdog_enabled}",
                )
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        with stream_lock:
            current_streams = list(active_streams.values())
        for stream in current_streams:
            try:
                stream.stop()
            except Exception:
                pass
        for thread in threads:
            thread.join(timeout=5.0)
        watchdog_thread.join(timeout=2.0)
        store.heartbeat("stopped")


def configured_stream_symbols() -> tuple[list[str], list[str]]:
    # Current Alpaca Basic limits are intentionally enforced as conservative
    # local caps. Paid entitlements can raise these through a future explicit
    # configuration change rather than accidental oversubscription.
    stock_symbols = _symbols(
        os.getenv("STREAM_STOCK_SYMBOLS", "SPY,QQQ,IWM"),
        30,
    )
    option_contracts = _symbols(
        os.getenv("STREAM_OPTION_CONTRACTS", ""),
        200,
    )
    return stock_symbols, option_contracts
