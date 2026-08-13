from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import requests

from .trade_quote_flow import analyze_trade_quote_rows


@dataclass(frozen=True)
class StreamStats:
    source: str
    live: bool
    events_seen: int
    valid_timesales: int
    reconnects: int
    symbols_subscribed: int
    started_at: str
    ended_at: str
    last_event_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _epoch_ms_iso(value: Any) -> str | None:
    try:
        millis = int(float(value))
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc).isoformat()


def normalize_timesale(event: dict[str, Any]) -> dict[str, Any] | None:
    if str(event.get("type") or "").lower() != "timesale":
        return None
    if bool(event.get("cancel")) or bool(event.get("correction")):
        return None
    session = str(event.get("session") or "normal").lower()
    if session not in {"normal", "open", "regular"}:
        return None
    timestamp = _epoch_ms_iso(event.get("date"))
    symbol = str(event.get("symbol") or "").replace(" ", "").upper()
    if not symbol or not timestamp:
        return None
    return {
        "contract_symbol": symbol,
        "timestamp": timestamp,
        "price": event.get("last"),
        "trade_price": event.get("last"),
        "bid": event.get("bid"),
        "ask": event.get("ask"),
        "size": event.get("size"),
        "trade_size": event.get("size"),
        "exchange": event.get("exch"),
        "exchange_code": event.get("exch"),
        "sequence": event.get("seq"),
        "flag": event.get("flag"),
    }


class RollingFlowBook:
    def __init__(self, *, retention_seconds: float = 12.0, burst_ms: int = 1500):
        self.retention_seconds = max(2.0, float(retention_seconds))
        self.burst_ms = max(250, int(burst_ms))
        self._rows: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        self._last_emitted: dict[str, tuple[int, int, str]] = {}

    @staticmethod
    def _epoch(row: dict[str, Any]) -> float:
        try:
            return datetime.fromisoformat(str(row["timestamp"])).timestamp()
        except (KeyError, TypeError, ValueError):
            return time.time()

    def add(self, row: dict[str, Any]) -> dict[str, Any] | None:
        contract = str(row.get("contract_symbol") or "")
        if not contract:
            return None
        bucket = self._rows[contract]
        bucket.append(row)
        cutoff = self._epoch(row) - self.retention_seconds
        while bucket and self._epoch(bucket[0]) < cutoff:
            bucket.popleft()
        evidence = analyze_trade_quote_rows(bucket, burst_ms=self.burst_ms)
        if not evidence.sweep_like_pattern:
            return None
        fingerprint = (evidence.trades, evidence.contracts, evidence.last_trade_at or "")
        if self._last_emitted.get(contract) == fingerprint:
            return None
        self._last_emitted[contract] = fingerprint
        payload = evidence.as_dict()
        payload["source"] = "tradier_timesale_live"
        payload["trade_quote_level"] = True
        payload["directional_interpretation"] = (
            "ask_side_demand_proxy" if evidence.aggressor_proxy == "ask" else "bid_side_supply_proxy"
        )
        return payload


class TradierOptionStream:
    """Single-session Tradier market-data WebSocket with bounded reconnects."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = "https://api.tradier.com",
        timeout_seconds: int = 20,
        allow_delayed_sandbox: bool = False,
    ):
        self.token = str(token or "").strip()
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout_seconds = max(5, int(timeout_seconds))
        self.allow_delayed_sandbox = bool(allow_delayed_sandbox)
        if not self.token:
            raise ValueError("TRADIER_TOKEN is required for streaming")
        if "sandbox" in self.base_url.lower() and not self.allow_delayed_sandbox:
            raise ValueError("Tradier sandbox is delayed and is not allowed for live-flow classification")

    @property
    def is_live(self) -> bool:
        return "sandbox" not in self.base_url.lower()

    @property
    def websocket_url(self) -> str:
        if self.is_live:
            return "wss://ws.tradier.com/v1/markets/events"
        return "wss://sandbox-ws.tradier.com/v1/markets/events"

    def create_session(self) -> str:
        response = requests.post(
            f"{self.base_url}/v1/markets/events/session",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        session_id = str(
            payload.get("stream", {}).get("sessionid")
            or payload.get("sessionid")
            or ""
        ).strip()
        if not session_id:
            raise RuntimeError("Tradier streaming session response did not contain sessionid")
        return session_id

    async def consume(
        self,
        symbols: list[str],
        *,
        duration_seconds: int,
        on_evidence: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
        max_reconnects: int = 5,
    ) -> tuple[StreamStats, list[dict[str, Any]]]:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets dependency is required for Tradier streaming") from exc

        normalized = list(dict.fromkeys(str(value or "").replace(" ", "").upper() for value in symbols if str(value or "").strip()))
        if not normalized:
            raise ValueError("At least one option contract symbol is required")
        duration = max(5, int(duration_seconds))
        started = datetime.now(timezone.utc)
        deadline = time.monotonic() + duration
        reconnects = 0
        events_seen = 0
        valid_timesales = 0
        last_event_at: str | None = None
        book = RollingFlowBook()
        evidence_rows: list[dict[str, Any]] = []

        while time.monotonic() < deadline:
            try:
                session_id = await asyncio.to_thread(self.create_session)
                async with websockets.connect(
                    self.websocket_url,
                    compression=None,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**22,
                ) as websocket:
                    subscription = {
                        "symbols": normalized,
                        "filter": ["timesale"],
                        "sessionid": session_id,
                        "linebreak": False,
                        "validOnly": True,
                        "advancedDetails": True,
                    }
                    await websocket.send(json.dumps(subscription))
                    while time.monotonic() < deadline:
                        remaining = max(0.1, min(30.0, deadline - time.monotonic()))
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                        except asyncio.TimeoutError:
                            if time.monotonic() >= deadline:
                                break
                            continue
                        events_seen += 1
                        try:
                            decoded = json.loads(message)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        batch = decoded if isinstance(decoded, list) else [decoded]
                        for event in batch:
                            if not isinstance(event, dict):
                                continue
                            row = normalize_timesale(event)
                            if row is None:
                                continue
                            valid_timesales += 1
                            last_event_at = row["timestamp"]
                            evidence = book.add(row)
                            if evidence is None:
                                continue
                            evidence_rows.append(evidence)
                            if on_evidence is not None:
                                result = on_evidence(evidence)
                                if asyncio.iscoroutine(result):
                                    await result
                if time.monotonic() >= deadline:
                    break
            except Exception:
                reconnects += 1
                if reconnects > max_reconnects or time.monotonic() >= deadline:
                    raise
                await asyncio.sleep(min(15.0, 1.5 * (2 ** (reconnects - 1))))

        ended = datetime.now(timezone.utc)
        stats = StreamStats(
            source="tradier",
            live=self.is_live,
            events_seen=events_seen,
            valid_timesales=valid_timesales,
            reconnects=reconnects,
            symbols_subscribed=len(normalized),
            started_at=started.isoformat(),
            ended_at=ended.isoformat(),
            last_event_at=last_event_at,
        )
        return stats, evidence_rows
