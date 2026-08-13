from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class TradeQuoteEvidence:
    contract_symbol: str
    trades: int
    contracts: int
    premium: float
    ask_side_contracts: int
    bid_side_contracts: int
    mid_contracts: int
    exchanges: tuple[str, ...]
    first_trade_at: str | None
    last_trade_at: str | None
    repeated_across_exchanges: bool
    burst_window_ms: int | None
    aggressor_proxy: str
    sweep_like_pattern: bool
    sweep_confirmed: bool
    opening_position_confirmed: bool
    evidence_note: str

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["exchanges"] = list(self.exchanges)
        return payload


def classify_trade(price: Any, bid: Any, ask: Any) -> str:
    px = _number(price)
    b = _number(bid)
    a = _number(ask)
    if px <= 0 or b <= 0 or a <= 0 or a < b:
        return "unknown"
    spread = max(a - b, 1e-9)
    position = (px - b) / spread
    if position >= 0.75:
        return "ask"
    if position <= 0.25:
        return "bid"
    return "mid"


def analyze_trade_quote_rows(
    rows: Iterable[dict[str, Any]],
    *,
    burst_ms: int = 1500,
    minimum_exchanges: int = 2,
    minimum_trades: int = 3,
) -> TradeQuoteEvidence:
    trades = [dict(row) for row in rows if isinstance(row, dict)]
    contract = str((trades[0] if trades else {}).get("contract_symbol") or "")
    timed = [(row, _time(row.get("timestamp") or row.get("trade_time"))) for row in trades]
    timed = [(row, ts) for row, ts in timed if ts is not None]
    timed.sort(key=lambda item: item[1])

    ask_contracts = 0
    bid_contracts = 0
    mid_contracts = 0
    total_contracts = 0
    premium = 0.0
    exchanges: set[str] = set()
    for row in trades:
        size = max(0, int(_number(row.get("size") or row.get("trade_size"))))
        price = _number(row.get("price") or row.get("trade_price"))
        side = classify_trade(price, row.get("bid"), row.get("ask"))
        total_contracts += size
        premium += size * price * 100.0
        if side == "ask":
            ask_contracts += size
        elif side == "bid":
            bid_contracts += size
        else:
            mid_contracts += size
        exchange = str(row.get("exchange") or row.get("exchange_code") or "").strip().upper()
        if exchange:
            exchanges.add(exchange)

    if ask_contracts > bid_contracts * 1.5:
        aggressor = "ask"
    elif bid_contracts > ask_contracts * 1.5:
        aggressor = "bid"
    else:
        aggressor = "mixed"

    first = timed[0][1] if timed else None
    last = timed[-1][1] if timed else None
    window = int((last - first).total_seconds() * 1000) if first and last else None
    repeated = len(exchanges) >= minimum_exchanges
    sweep_like = bool(
        len(trades) >= minimum_trades
        and repeated
        and window is not None
        and window <= burst_ms
        and aggressor in {"ask", "bid"}
    )

    return TradeQuoteEvidence(
        contract_symbol=contract,
        trades=len(trades),
        contracts=total_contracts,
        premium=round(premium, 2),
        ask_side_contracts=ask_contracts,
        bid_side_contracts=bid_contracts,
        mid_contracts=mid_contracts,
        exchanges=tuple(sorted(exchanges)),
        first_trade_at=first.isoformat() if first else None,
        last_trade_at=last.isoformat() if last else None,
        repeated_across_exchanges=repeated,
        burst_window_ms=window,
        aggressor_proxy=aggressor,
        sweep_like_pattern=sweep_like,
        sweep_confirmed=False,
        opening_position_confirmed=False,
        evidence_note=(
            "Trade+NBBO evidence can identify a sweep-like multi-exchange burst and aggressor proxy. "
            "It still does not prove beneficial-owner intent or Buy-to-Open; next-session OI/change-in-position evidence is required for that claim."
        ),
    )
