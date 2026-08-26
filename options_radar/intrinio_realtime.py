from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from options_radar.realtime_flow import RealtimeFlowService, RealtimeOptionEvent, parse_option_contract


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _event_time(value: Any) -> datetime:
    raw = _float(value)
    if raw <= 0:
        return datetime.now(timezone.utc)
    # Intrinio realtime SDK currently exposes seconds as float, but this keeps
    # normalization robust if a transport returns milliseconds/nanoseconds.
    if raw > 1e16:
        raw /= 1e9
    elif raw > 1e11:
        raw /= 1e3
    return datetime.fromtimestamp(raw, tz=timezone.utc)


def _enum_name(value: Any) -> str:
    name = getattr(value, "name", None)
    return str(name or value or "").upper().strip()


def trade_to_event(trade: Any, *, delayed: bool = False) -> RealtimeOptionEvent | None:
    contract = str(getattr(trade, "contract", "") or "").upper().strip()
    parsed = parse_option_contract(contract)
    if not parsed["underlying"]:
        return None
    event_at = _event_time(getattr(trade, "timestamp", 0))
    qualifiers = tuple(
        _int(value)
        for value in (getattr(trade, "qualifiers", ()) or ())
        if _int(value, -1) >= 0
    )
    exchange = _enum_name(getattr(trade, "exchange", ""))
    return RealtimeOptionEvent(
        provider="intrinio-opra",
        kind="trade",
        contract=contract,
        underlying=parsed["underlying"],
        option_type=parsed["option_type"],
        strike=parsed["strike"],
        expiration=parsed["expiration"],
        event_at=event_at,
        received_at=datetime.now(timezone.utc),
        data_mode="delayed" if delayed else "realtime",
        price=_float(getattr(trade, "price", 0)),
        size=_int(getattr(trade, "size", 0)),
        total_value=0.0,
        bid=_float(getattr(trade, "bid_price_at_execution", 0)),
        ask=_float(getattr(trade, "ask_price_at_execution", 0)),
        underlying_price=_float(getattr(trade, "underlying_price_at_execution", 0)),
        exchange=exchange,
        qualifiers=qualifiers,
        total_volume=_int(getattr(trade, "total_volume", 0)),
    )


def unusual_activity_to_event(activity: Any, *, delayed: bool = False) -> RealtimeOptionEvent | None:
    contract = str(getattr(activity, "contract", "") or "").upper().strip()
    parsed = parse_option_contract(contract)
    if not parsed["underlying"]:
        return None
    event_at = _event_time(getattr(activity, "timestamp", 0))
    return RealtimeOptionEvent(
        provider="intrinio-opra",
        kind="unusual",
        contract=contract,
        underlying=parsed["underlying"],
        option_type=parsed["option_type"],
        strike=parsed["strike"],
        expiration=parsed["expiration"],
        event_at=event_at,
        received_at=datetime.now(timezone.utc),
        data_mode="delayed" if delayed else "realtime",
        price=_float(getattr(activity, "average_price", 0)),
        size=_int(getattr(activity, "total_size", 0)),
        total_value=_float(getattr(activity, "total_value", 0)),
        bid=_float(getattr(activity, "bid_price_at_execution", 0)),
        ask=_float(getattr(activity, "ask_price_at_execution", 0)),
        underlying_price=_float(getattr(activity, "underlying_price_at_execution", 0)),
        activity_type=_enum_name(getattr(activity, "activity_type", "")),
        sentiment=_enum_name(getattr(activity, "sentiment", "")),
    )


@dataclass(frozen=True)
class IntrinioRealtimeConfig:
    api_key: str
    symbols: tuple[str, ...]
    provider: str = "OPRA"
    delayed: bool = False
    num_threads: int = 8
    firehose: bool = False

    @classmethod
    def from_env(cls, symbols: list[str] | tuple[str, ...] | None = None) -> "IntrinioRealtimeConfig":
        raw_symbols = symbols or tuple(
            value.strip().upper()
            for value in os.getenv("OPTIONS_REALTIME_SYMBOLS", "").split(",")
            if value.strip()
        )
        source = os.getenv("INTRINIO_OPTIONS_SOURCE", "delayed").strip().lower()
        delayed = source != "realtime"
        return cls(
            api_key=os.getenv("INTRINIO_API_KEY", "").strip(),
            symbols=tuple(dict.fromkeys(raw_symbols)),
            provider=os.getenv("INTRINIO_REALTIME_PROVIDER", "OPRA").strip().upper() or "OPRA",
            delayed=delayed,
            num_threads=max(1, min(32, _int(os.getenv("INTRINIO_REALTIME_THREADS", "8"), 8))),
            firehose=os.getenv("INTRINIO_REALTIME_FIREHOSE", "false").strip().lower() in {"1", "true", "yes", "on"},
        )


class IntrinioRealtimeAdapter:
    """Thin provider adapter. Callbacks only normalize and enqueue events."""

    def __init__(self, service: RealtimeFlowService, config: IntrinioRealtimeConfig | None = None) -> None:
        self.service = service
        self.config = config or IntrinioRealtimeConfig.from_env()
        self.client: Any = None

    @property
    def ready(self) -> bool:
        return bool(self.config.api_key and (self.config.symbols or self.config.firehose))

    def build_client(self) -> Any:
        if not self.config.api_key:
            raise RuntimeError("INTRINIO_API_KEY is required for realtime options")
        if not self.config.symbols and not self.config.firehose:
            raise RuntimeError("OPTIONS_REALTIME_SYMBOLS is empty and firehose is disabled")
        try:
            from intriniorealtime.options_client import (
                Config,
                IntrinioRealtimeOptionsClient,
                LogLevel,
                Providers,
            )
        except ImportError as exc:
            raise RuntimeError(
                "intriniorealtime is not installed; install requirements-realtime.txt"
            ) from exc

        provider = getattr(Providers, self.config.provider, None)
        if provider is None:
            raise RuntimeError(f"Unsupported Intrinio realtime provider: {self.config.provider}")

        def on_trade(trade: Any) -> None:
            event = trade_to_event(trade, delayed=self.config.delayed)
            if event is not None:
                self.service.submit(event)

        def on_unusual_activity(activity: Any) -> None:
            event = unusual_activity_to_event(activity, delayed=self.config.delayed)
            if event is not None:
                self.service.submit(event)

        config = Config(
            api_key=self.config.api_key,
            provider=provider,
            num_threads=self.config.num_threads,
            symbols=list(self.config.symbols),
            log_level=LogLevel.INFO,
            delayed=self.config.delayed,
        )
        self.client = IntrinioRealtimeOptionsClient(
            config,
            on_trade=on_trade,
            on_unusual_activity=on_unusual_activity,
        )
        return self.client

    def start(self) -> None:
        client = self.client or self.build_client()
        self.service.start()
        client.start()
        if self.config.firehose:
            client.join_firehose()
        else:
            client.join()

    def stop(self) -> None:
        if self.client is not None:
            try:
                self.client.stop()
            finally:
                self.service.stop()
        else:
            self.service.stop()

    def stats(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "provider": self.config.provider,
            "data_mode": "delayed" if self.config.delayed else "realtime",
            "symbols": list(self.config.symbols),
            "firehose": self.config.firehose,
            "service": self.service.stats(),
        }
        if self.client is not None:
            try:
                data_msgs, text_msgs, queue_depth = self.client.get_stats()
                data["provider_stats"] = {
                    "data_messages": int(data_msgs),
                    "text_messages": int(text_msgs),
                    "sdk_queue_depth": int(queue_depth),
                }
            except Exception:
                data["provider_stats"] = {"status": "unavailable"}
        return data
