from __future__ import annotations

import hashlib
import math
import queue
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


COMPLEX_QUALIFIERS = frozenset({12, 13, 16, 17, 32, 33, 34, 35, 36, 87, 222})
ISO_QUALIFIERS = frozenset({19, 23, 28, 30})
BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_option_contract(contract: str) -> dict[str, Any]:
    """Parse Intrinio/OCC-style option symbols without depending on a vendor SDK."""
    raw = str(contract or "").strip().upper()
    raw = raw[2:] if raw.startswith("O:") else raw
    compact = re.sub(r"\s+", "", raw)
    match = re.match(r"^([A-Z0-9./-]{1,6})_*?(\d{6})([CP])(\d{8})$", compact)
    if not match:
        return {
            "contract": raw,
            "underlying": "",
            "expiration": "",
            "option_type": "",
            "strike": 0.0,
        }
    underlying, yymmdd, option_type, strike_raw = match.groups()
    try:
        expiration = datetime.strptime(yymmdd, "%y%m%d").date().isoformat()
    except ValueError:
        expiration = ""
    return {
        "contract": raw,
        "underlying": underlying.rstrip("_"),
        "expiration": expiration,
        "option_type": "CALL" if option_type == "C" else "PUT",
        "strike": int(strike_raw) / 1000.0,
    }


def execution_side(price: float, bid: float, ask: float) -> str:
    """Classify only when execution is clearly at/through the displayed market."""
    price = _num(price)
    bid = _num(bid)
    ask = _num(ask)
    if price <= 0:
        return "UNKNOWN"
    tolerance = max(0.005, price * 0.0005)
    if ask > 0 and price >= ask - tolerance:
        return "BUYER"
    if bid > 0 and price <= bid + tolerance:
        return "SELLER"
    return "MID"


def infer_bias(option_type: str, side: str, sentiment: str = "") -> str:
    sentiment = str(sentiment or "").upper()
    if sentiment in {BULLISH, BEARISH}:
        return sentiment
    option_type = str(option_type or "").upper()
    side = str(side or "").upper()
    if option_type == "CALL":
        return BULLISH if side == "BUYER" else BEARISH if side == "SELLER" else NEUTRAL
    if option_type == "PUT":
        return BEARISH if side == "BUYER" else BULLISH if side == "SELLER" else NEUTRAL
    return NEUTRAL


@dataclass(frozen=True)
class RealtimeOptionEvent:
    provider: str
    kind: str
    contract: str
    underlying: str
    option_type: str
    strike: float
    expiration: str
    event_at: datetime
    received_at: datetime
    data_mode: str = "unknown"
    price: float = 0.0
    size: int = 0
    total_value: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    underlying_price: float = 0.0
    exchange: str = ""
    qualifiers: tuple[int, ...] = ()
    activity_type: str = ""
    sentiment: str = ""
    total_volume: int = 0

    @property
    def side(self) -> str:
        return execution_side(self.price, self.bid, self.ask)

    @property
    def bias(self) -> str:
        return infer_bias(self.option_type, self.side, self.sentiment)

    @property
    def is_realtime(self) -> bool:
        return self.data_mode.lower() == "realtime"

    @property
    def premium(self) -> float:
        if self.total_value > 0:
            return self.total_value
        return max(self.price, 0.0) * max(self.size, 0) * 100.0

    @property
    def complex_risk(self) -> bool:
        return bool(COMPLEX_QUALIFIERS.intersection(self.qualifiers))

    @property
    def iso_evidence(self) -> bool:
        return bool(ISO_QUALIFIERS.intersection(self.qualifiers))

    @property
    def sweep_confirmed(self) -> bool:
        return self.activity_type.upper() in {"SWEEP", "UNUSUAL_SWEEP"}

    @property
    def fingerprint(self) -> str:
        seed = "|".join(
            [
                self.provider,
                self.kind,
                self.contract,
                f"{self.event_at.timestamp():.6f}",
                f"{self.price:.6f}",
                str(self.size),
                f"{self.total_value:.2f}",
                self.activity_type,
                ",".join(str(v) for v in self.qualifiers),
            ]
        )
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


@dataclass
class ParentOrder:
    parent_id: str
    contract: str
    underlying: str
    option_type: str
    strike: float
    expiration: str
    bias: str
    first_at: datetime
    last_at: datetime
    first_underlying_price: float = 0.0
    last_underlying_price: float = 0.0
    premium: float = 0.0
    size: int = 0
    raw_event_count: int = 0
    provider_event_count: int = 0
    exchanges: set[str] = field(default_factory=set)
    activity_types: set[str] = field(default_factory=set)
    qualifiers: set[int] = field(default_factory=set)
    realtime_event_count: int = 0
    delayed_event_count: int = 0
    event_ids: set[str] = field(default_factory=set)

    @property
    def complex_risk(self) -> bool:
        return bool(COMPLEX_QUALIFIERS.intersection(self.qualifiers))

    @property
    def sweep_confirmed(self) -> bool:
        return bool({"SWEEP", "UNUSUAL_SWEEP"}.intersection(self.activity_types))

    @property
    def iso_evidence(self) -> bool:
        return bool(ISO_QUALIFIERS.intersection(self.qualifiers))

    @property
    def realtime(self) -> bool:
        return self.realtime_event_count > 0 and self.realtime_event_count >= self.delayed_event_count

    def absorb(self, event: RealtimeOptionEvent) -> None:
        if event.fingerprint in self.event_ids:
            return
        self.event_ids.add(event.fingerprint)
        self.last_at = max(self.last_at, event.event_at)
        if self.first_underlying_price <= 0 and event.underlying_price > 0:
            self.first_underlying_price = event.underlying_price
        if event.underlying_price > 0:
            self.last_underlying_price = event.underlying_price
        if event.kind == "unusual":
            # Provider unusual-activity events are already aggregated. Using max avoids
            # double-counting the same sweep when raw trade callbacks are also enabled.
            self.premium = max(self.premium, event.premium)
            self.size = max(self.size, max(event.size, 0))
            self.provider_event_count += 1
        else:
            # If the provider-aggregated unusual event already landed in this parent
            # window, keep raw prints as microstructure evidence but do not add their
            # premium/size again.
            if self.provider_event_count == 0:
                self.premium += max(event.premium, 0.0)
                self.size += max(event.size, 0)
            self.raw_event_count += 1
        if event.exchange:
            self.exchanges.add(event.exchange)
        if event.activity_type:
            self.activity_types.add(event.activity_type.upper())
        self.qualifiers.update(int(v) for v in event.qualifiers)
        if event.is_realtime:
            self.realtime_event_count += 1
        elif event.data_mode.lower() == "delayed":
            self.delayed_event_count += 1


class ParentOrderClusterer:
    """Conservatively reconstruct likely parent orders from rapid trade fragments."""

    def __init__(
        self,
        *,
        parent_window_ms: int = 2500,
        retention_seconds: int = 900,
        max_seen_events: int = 50000,
    ) -> None:
        self.parent_window_ms = max(100, int(parent_window_ms))
        self.retention_seconds = max(30, int(retention_seconds))
        self.max_seen_events = max(1000, int(max_seen_events))
        self.orders: list[ParentOrder] = []
        self._seen: dict[str, datetime] = {}

    def _purge(self, now: datetime) -> None:
        cutoff = now.timestamp() - self.retention_seconds
        self.orders = [order for order in self.orders if order.last_at.timestamp() >= cutoff]
        if len(self._seen) > self.max_seen_events:
            kept = sorted(self._seen.items(), key=lambda item: item[1], reverse=True)[: self.max_seen_events // 2]
            self._seen = dict(kept)

    def _compatible(self, order: ParentOrder, event: RealtimeOptionEvent) -> bool:
        if order.contract != event.contract:
            return False
        elapsed_ms = abs((event.event_at - order.last_at).total_seconds() * 1000.0)
        if elapsed_ms > self.parent_window_ms:
            return False
        if order.bias != NEUTRAL and event.bias != NEUTRAL and order.bias != event.bias:
            return False
        reference = 0.0
        if order.size > 0 and order.premium > 0:
            reference = order.premium / max(order.size * 100.0, 1.0)
        if reference > 0 and event.price > 0:
            tolerance = max(0.08, reference * 0.04)
            if abs(reference - event.price) > tolerance:
                return False
        return True

    def ingest(self, event: RealtimeOptionEvent, *, now: datetime | None = None) -> ParentOrder | None:
        now = _utc(now or event.received_at)
        self._purge(now)
        if event.fingerprint in self._seen:
            return None
        self._seen[event.fingerprint] = now

        match: ParentOrder | None = None
        for order in reversed(self.orders):
            if self._compatible(order, event):
                match = order
                break

        if match is None:
            seed = f"{event.underlying}|{event.contract}|{event.bias}|{event.event_at.timestamp():.6f}"
            match = ParentOrder(
                parent_id=hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16],
                contract=event.contract,
                underlying=event.underlying,
                option_type=event.option_type,
                strike=event.strike,
                expiration=event.expiration,
                bias=event.bias,
                first_at=event.event_at,
                last_at=event.event_at,
                first_underlying_price=event.underlying_price,
                last_underlying_price=event.underlying_price,
            )
            self.orders.append(match)

        match.absorb(event)
        if match.bias == NEUTRAL and event.bias != NEUTRAL:
            match.bias = event.bias
        return match


@dataclass(frozen=True)
class ThesisSnapshot:
    thesis_id: str
    underlying: str
    bias: str
    stage: str
    evidence_grade: str
    actionable: bool
    parent_orders: int
    realtime_parent_orders: int
    total_premium: float
    opposing_premium: float
    distinct_strikes: int
    strikes: tuple[float, ...]
    sweep_parent_orders: int
    iso_parent_orders: int
    complex_parent_orders: int
    complex_ratio: float
    freshest_age_seconds: float
    price_state: str
    aligned_underlying_move_pct: float
    first_seen_at: str
    last_seen_at: str
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "thesis_id": self.thesis_id,
            "underlying": self.underlying,
            "bias": self.bias,
            "stage": self.stage,
            "evidence_grade": self.evidence_grade,
            "actionable": self.actionable,
            "parent_orders": self.parent_orders,
            "realtime_parent_orders": self.realtime_parent_orders,
            "total_premium": round(self.total_premium, 2),
            "opposing_premium": round(self.opposing_premium, 2),
            "distinct_strikes": self.distinct_strikes,
            "strikes": list(self.strikes),
            "sweep_parent_orders": self.sweep_parent_orders,
            "iso_parent_orders": self.iso_parent_orders,
            "complex_parent_orders": self.complex_parent_orders,
            "complex_ratio": round(self.complex_ratio, 4),
            "freshest_age_seconds": round(self.freshest_age_seconds, 3),
            "price_state": self.price_state,
            "aligned_underlying_move_pct": round(self.aligned_underlying_move_pct, 4),
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "reasons": list(self.reasons),
        }


class RealtimeFlowEngine:
    """Hot-path options flow engine.

    The engine intentionally separates evidence from probability. It outputs a
    categorical evidence grade and never interprets A/A+ as a win rate.
    """

    def __init__(
        self,
        *,
        thesis_window_seconds: int = 600,
        max_event_age_seconds: int = 90,
        min_confirmed_premium: float = 250_000.0,
        extended_move_pct: float = 0.80,
        clusterer: ParentOrderClusterer | None = None,
    ) -> None:
        self.thesis_window_seconds = max(60, int(thesis_window_seconds))
        self.max_event_age_seconds = max(10, int(max_event_age_seconds))
        self.min_confirmed_premium = max(1.0, float(min_confirmed_premium))
        self.extended_move_pct = max(0.10, float(extended_move_pct))
        self.clusterer = clusterer or ParentOrderClusterer(retention_seconds=self.thesis_window_seconds + 300)

    def _orders(self, underlying: str, bias: str, now: datetime) -> list[ParentOrder]:
        cutoff = now.timestamp() - self.thesis_window_seconds
        return [
            order
            for order in self.clusterer.orders
            if order.underlying == underlying
            and order.bias == bias
            and order.last_at.timestamp() >= cutoff
        ]

    def _snapshot(self, underlying: str, bias: str, now: datetime) -> ThesisSnapshot | None:
        orders = self._orders(underlying, bias, now)
        if not orders:
            return None
        opposite = BEARISH if bias == BULLISH else BULLISH
        opposite_orders = self._orders(underlying, opposite, now)

        orders.sort(key=lambda order: order.first_at)
        total_premium = sum(max(order.premium, 0.0) for order in orders)
        opposite_premium = sum(max(order.premium, 0.0) for order in opposite_orders)
        realtime_orders = [order for order in orders if order.realtime]
        realtime_premium = sum(max(order.premium, 0.0) for order in realtime_orders)
        complex_orders = [order for order in orders if order.complex_risk]
        sweeps = [order for order in orders if order.sweep_confirmed]
        iso_orders = [order for order in orders if order.iso_evidence]
        strikes = tuple(sorted({round(order.strike, 6) for order in orders if order.strike > 0}))
        newest = max(order.last_at for order in orders)
        oldest = min(order.first_at for order in orders)
        freshest_age = max(0.0, (now - newest).total_seconds())

        first_price = next((order.first_underlying_price for order in orders if order.first_underlying_price > 0), 0.0)
        last_price = next((order.last_underlying_price for order in reversed(orders) if order.last_underlying_price > 0), 0.0)
        raw_move = (last_price / first_price - 1.0) * 100.0 if first_price > 0 and last_price > 0 else 0.0
        aligned_move = raw_move if bias == BULLISH else -raw_move
        if aligned_move <= -0.35:
            price_state = "DIVERGING"
        elif aligned_move < 0.20:
            price_state = "LAGGING"
        elif aligned_move <= self.extended_move_pct:
            price_state = "CONFIRMING"
        else:
            price_state = "EXTENDED"

        parent_count = len(orders)
        complex_ratio = len(complex_orders) / max(parent_count, 1)
        realtime_ratio = len(realtime_orders) / max(parent_count, 1)
        realtime_premium_ratio = realtime_premium / max(total_premium, 1.0)
        fresh_enough = freshest_age <= self.max_event_age_seconds
        opposed = opposite_premium >= max(self.min_confirmed_premium, total_premium * 1.25)

        structure_ok = len(sweeps) >= 1 or len(strikes) >= 2 or len(iso_orders) >= 2
        confirmed = (
            parent_count >= 2
            and total_premium >= self.min_confirmed_premium
            and structure_ok
            and fresh_enough
            and realtime_ratio >= 0.67
            and realtime_premium_ratio >= 0.67
            and complex_ratio <= 0.34
            and not opposed
        )

        if opposed and opposite_premium > total_premium:
            stage = "FAILED"
        elif confirmed and price_state == "EXTENDED":
            stage = "EXTENDED"
        elif confirmed:
            stage = "CONFIRMED"
        elif parent_count >= 2 or len(strikes) >= 2 or total_premium >= self.min_confirmed_premium * 0.5:
            stage = "BUILDING"
        else:
            stage = "WATCH"

        if (
            confirmed
            and parent_count >= 3
            and total_premium >= 750_000
            and (len(sweeps) >= 2 or len(strikes) >= 3)
            and complex_ratio <= 0.20
        ):
            grade = "A+"
        elif confirmed:
            grade = "A"
        elif stage == "BUILDING" and realtime_orders and total_premium >= 100_000:
            grade = "B"
        else:
            grade = "C"

        actionable = (
            stage == "CONFIRMED"
            and grade in {"A", "A+"}
            and price_state in {"LAGGING", "CONFIRMING"}
            and fresh_enough
        )

        reasons: list[str] = []
        reasons.append(f"{parent_count} parent orders")
        reasons.append(f"${total_premium:,.0f} premium")
        if sweeps:
            reasons.append(f"{len(sweeps)} provider-confirmed sweep(s)")
        elif iso_orders:
            reasons.append(f"{len(iso_orders)} ISO-qualified parent order(s)")
        if len(strikes) >= 2:
            reasons.append(f"{len(strikes)} strikes")
        if complex_orders:
            reasons.append(f"complex-risk {complex_ratio:.0%}")
        if not fresh_enough:
            reasons.append(f"stale {freshest_age:.0f}s")
        if realtime_ratio < 0.67 or realtime_premium_ratio < 0.67:
            reasons.append("insufficient realtime evidence")
        if opposed:
            reasons.append("opposing flow dominates")

        thesis_seed = f"{underlying}|{bias}|{oldest.date().isoformat()}"
        thesis_id = hashlib.sha1(thesis_seed.encode("utf-8")).hexdigest()[:12]
        return ThesisSnapshot(
            thesis_id=thesis_id,
            underlying=underlying,
            bias=bias,
            stage=stage,
            evidence_grade=grade,
            actionable=actionable,
            parent_orders=parent_count,
            realtime_parent_orders=len(realtime_orders),
            total_premium=total_premium,
            opposing_premium=opposite_premium,
            distinct_strikes=len(strikes),
            strikes=strikes[:10],
            sweep_parent_orders=len(sweeps),
            iso_parent_orders=len(iso_orders),
            complex_parent_orders=len(complex_orders),
            complex_ratio=complex_ratio,
            freshest_age_seconds=freshest_age,
            price_state=price_state,
            aligned_underlying_move_pct=aligned_move,
            first_seen_at=oldest.isoformat(),
            last_seen_at=newest.isoformat(),
            reasons=tuple(reasons),
        )

    def ingest(self, event: RealtimeOptionEvent, *, now: datetime | None = None) -> ThesisSnapshot | None:
        now = _utc(now or event.received_at)
        if not event.underlying or event.bias == NEUTRAL:
            self.clusterer.ingest(event, now=now)
            return None
        order = self.clusterer.ingest(event, now=now)
        if order is None:
            return self._snapshot(event.underlying, event.bias, now)
        return self._snapshot(order.underlying, order.bias, now)

    def snapshot_all(self, *, now: datetime | None = None) -> list[ThesisSnapshot]:
        now = _utc(now)
        keys = {
            (order.underlying, order.bias)
            for order in self.clusterer.orders
            if order.underlying and order.bias in {BULLISH, BEARISH}
        }
        snapshots = [self._snapshot(symbol, bias, now) for symbol, bias in sorted(keys)]
        return [snapshot for snapshot in snapshots if snapshot is not None]


class RealtimeFlowService:
    """Queue-backed service so market-data callbacks stay tiny and non-blocking."""

    def __init__(
        self,
        engine: RealtimeFlowEngine | None = None,
        *,
        on_snapshot: Callable[[ThesisSnapshot], None] | None = None,
        queue_size: int = 20000,
    ) -> None:
        self.engine = engine or RealtimeFlowEngine()
        self.on_snapshot = on_snapshot
        self.queue: queue.Queue[RealtimeOptionEvent] = queue.Queue(maxsize=max(100, int(queue_size)))
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self._run, name="options-flow-worker", daemon=True)
        self.submitted = 0
        self.processed = 0
        self.dropped = 0
        self.callback_errors = 0

    def start(self) -> None:
        if not self.worker.is_alive():
            self.worker.start()

    def submit(self, event: RealtimeOptionEvent) -> bool:
        try:
            self.queue.put_nowait(event)
            self.submitted += 1
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def _run(self) -> None:
        while not self.stop_event.is_set() or not self.queue.empty():
            try:
                event = self.queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                snapshot = self.engine.ingest(event)
                self.processed += 1
                if snapshot is not None and self.on_snapshot is not None:
                    try:
                        self.on_snapshot(snapshot)
                    except Exception:
                        self.callback_errors += 1
            finally:
                self.queue.task_done()

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        if self.worker.is_alive():
            self.worker.join(timeout=max(0.1, timeout))

    def stats(self) -> dict[str, int]:
        return {
            "submitted": self.submitted,
            "processed": self.processed,
            "dropped": self.dropped,
            "callback_errors": self.callback_errors,
            "queue_depth": self.queue.qsize(),
        }
