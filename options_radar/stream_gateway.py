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


@dataclass
class SnapshotStore:
    path: Path
    stock_feed: str
    option_feed: str
    flush_interval_seconds: float = 0.75
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_flush_monotonic: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.payload = {
            "schema_version": 1,
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
            },
        }

    def update(self, asset: str, event: Any) -> None:
        row = _plain(event)
        if not isinstance(row, dict):
            return
        symbol = str(row.get("S") or row.get("symbol") or "").upper().replace(" ", "")
        if not symbol:
            return
        event_type = str(row.get("T") or row.get("type") or "event").lower()
        now = _now()
        with self.lock:
            bucket = self.payload["stocks"] if asset == "stock" else self.payload["options"]
            record = bucket.setdefault(symbol, {})
            record[event_type] = row
            record["last_event_at"] = now
            health_key = "stock_events" if asset == "stock" else "option_events"
            self.payload["health"][health_key] = int(self.payload["health"].get(health_key, 0)) + 1
            self.payload["health"]["last_event_at"] = now
            self.payload["generated_at"] = now
        self.flush_if_due()

    def heartbeat(self, status: str, detail: str = "") -> None:
        with self.lock:
            self.payload["health"]["status"] = status
            self.payload["health"]["detail"] = detail[:500]
            self.payload["health"]["heartbeat_at"] = _now()
            self.payload["generated_at"] = _now()
        self.flush(force=True)

    def flush_if_due(self) -> None:
        if time.monotonic() - self.last_flush_monotonic >= self.flush_interval_seconds:
            self.flush()

    def flush(self, force: bool = False) -> None:
        with self.lock:
            if not force and time.monotonic() - self.last_flush_monotonic < self.flush_interval_seconds:
                return
            snapshot = json.loads(json.dumps(self.payload, default=str))
            self.last_flush_monotonic = time.monotonic()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.path)


def run_alpaca_gateway(
    *,
    stock_symbols: list[str],
    option_contracts: list[str],
    snapshot_path: str | Path,
    run_seconds: int = 0,
) -> None:
    """Run stock and option streams in parallel using Alpaca's official SDK.

    The free plan can use IEX stocks and indicative options. If OPRA/SIP
    entitlements are added later, changing the feed environment variables is
    enough; the downstream fabric consumes the same snapshot schema.
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
        raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required for streaming")

    stock_feed_name = str(os.getenv("ALPACA_STOCK_FEED", "iex") or "iex").lower()
    option_feed_name = str(os.getenv("ALPACA_OPTIONS_FEED", "indicative") or "indicative").lower()
    stock_feed = DataFeed.SIP if stock_feed_name == "sip" else DataFeed.IEX
    option_feed = OptionsFeed.OPRA if option_feed_name == "opra" else OptionsFeed.INDICATIVE

    store = SnapshotStore(Path(snapshot_path), stock_feed_name, option_feed_name)
    stop_event = threading.Event()
    streams: list[Any] = []

    async def stock_quote(event: Any) -> None:
        store.update("stock", event)

    async def stock_trade(event: Any) -> None:
        store.update("stock", event)

    async def option_quote(event: Any) -> None:
        store.update("option", event)

    async def option_trade(event: Any) -> None:
        store.update("option", event)

    def run_stock() -> None:
        backoff = 1.0
        while not stop_event.is_set() and stock_symbols:
            stream = StockDataStream(api_key, secret_key, raw_data=True, feed=stock_feed)
            streams.append(stream)
            stream.subscribe_quotes(stock_quote, *stock_symbols)
            stream.subscribe_trades(stock_trade, *stock_symbols)
            try:
                store.heartbeat("stock_connecting")
                stream.run()
                backoff = 1.0
            except Exception as exc:
                store.heartbeat("stock_reconnecting", f"{type(exc).__name__}: {exc}")
                if stop_event.wait(backoff):
                    break
                backoff = min(30.0, backoff * 2.0)

    def run_options() -> None:
        backoff = 1.0
        while not stop_event.is_set() and option_contracts:
            stream = OptionDataStream(api_key, secret_key, raw_data=True, feed=option_feed)
            streams.append(stream)
            stream.subscribe_quotes(option_quote, *option_contracts)
            stream.subscribe_trades(option_trade, *option_contracts)
            try:
                store.heartbeat("options_connecting")
                stream.run()
                backoff = 1.0
            except Exception as exc:
                store.heartbeat("options_reconnecting", f"{type(exc).__name__}: {exc}")
                if stop_event.wait(backoff):
                    break
                backoff = min(30.0, backoff * 2.0)

    threads: list[threading.Thread] = []
    if stock_symbols:
        threads.append(threading.Thread(target=run_stock, name="alpaca-stock-stream", daemon=True))
    if option_contracts:
        threads.append(threading.Thread(target=run_options, name="alpaca-option-stream", daemon=True))
    if not threads:
        raise RuntimeError("No stock symbols or option contracts were configured for streaming")

    for thread in threads:
        thread.start()
    store.heartbeat("running", f"stocks={len(stock_symbols)} options={len(option_contracts)}")

    try:
        if run_seconds > 0:
            stop_event.wait(run_seconds)
        else:
            while not stop_event.wait(5.0):
                store.heartbeat("running", f"stocks={len(stock_symbols)} options={len(option_contracts)}")
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        for stream in streams:
            try:
                stream.stop()
            except Exception:
                pass
        for thread in threads:
            thread.join(timeout=5.0)
        store.heartbeat("stopped")


def configured_stream_symbols() -> tuple[list[str], list[str]]:
    # Alpaca Basic currently documents limits of 30 equity WebSocket symbols and
    # 200 option quote subscriptions. Caps here prevent accidental over-subscribe.
    stock_symbols = _symbols(os.getenv("STREAM_STOCK_SYMBOLS", "SPY,QQQ,IWM"), 30)
    option_contracts = _symbols(os.getenv("STREAM_OPTION_CONTRACTS", ""), 200)
    return stock_symbols, option_contracts
