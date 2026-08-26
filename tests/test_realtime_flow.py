from datetime import datetime, timedelta, timezone

from options_radar.realtime_flow import (
    BULLISH,
    ParentOrderClusterer,
    RealtimeFlowEngine,
    RealtimeOptionEvent,
    parse_option_contract,
)


NOW = datetime(2026, 8, 26, 15, 0, tzinfo=timezone.utc)


def _event(
    *,
    contract: str = "NVDA__260828C00200000",
    at: datetime = NOW,
    kind: str = "unusual",
    premium: float = 300_000,
    price: float = 3.0,
    size: int = 1000,
    bid: float = 2.95,
    ask: float = 3.0,
    underlying_price: float = 200.0,
    sentiment: str = "BULLISH",
    activity_type: str = "SWEEP",
    data_mode: str = "realtime",
    qualifiers: tuple[int, ...] = (),
) -> RealtimeOptionEvent:
    parsed = parse_option_contract(contract)
    return RealtimeOptionEvent(
        provider="test",
        kind=kind,
        contract=contract,
        underlying=parsed["underlying"],
        option_type=parsed["option_type"],
        strike=parsed["strike"],
        expiration=parsed["expiration"],
        event_at=at,
        received_at=at,
        data_mode=data_mode,
        price=price,
        size=size,
        total_value=premium if kind == "unusual" else 0.0,
        bid=bid,
        ask=ask,
        underlying_price=underlying_price,
        qualifiers=qualifiers,
        activity_type=activity_type,
        sentiment=sentiment,
    )


def test_parse_intrinio_padded_contract():
    parsed = parse_option_contract("NVDA__260828C00200000")
    assert parsed["underlying"] == "NVDA"
    assert parsed["option_type"] == "CALL"
    assert parsed["expiration"] == "2026-08-28"
    assert parsed["strike"] == 200.0


def test_parent_order_merges_fragments_and_dedupes():
    clusterer = ParentOrderClusterer(parent_window_ms=2500)
    first = _event(kind="trade", premium=0, size=50)
    second = _event(kind="trade", premium=0, size=75, at=NOW + timedelta(milliseconds=700))
    one = clusterer.ingest(first, now=first.received_at)
    two = clusterer.ingest(second, now=second.received_at)
    duplicate = clusterer.ingest(second, now=second.received_at)
    assert one is two
    assert duplicate is None
    assert len(clusterer.orders) == 1
    assert two.raw_event_count == 2
    assert two.size == 125


def test_realtime_multi_strike_sweeps_confirm_thesis_without_probability_claim():
    engine = RealtimeFlowEngine()
    first = engine.ingest(_event(), now=NOW)
    second = engine.ingest(
        _event(
            contract="NVDA__260828C00205000",
            at=NOW + timedelta(seconds=10),
            underlying_price=200.10,
        ),
        now=NOW + timedelta(seconds=10),
    )
    assert first is not None and first.stage == "BUILDING"
    assert second is not None
    assert second.bias == "BULLISH"
    assert second.stage == "CONFIRMED"
    assert second.evidence_grade == "A"
    assert second.actionable is True
    assert second.distinct_strikes == 2


def test_delayed_evidence_cannot_be_confirmed():
    engine = RealtimeFlowEngine()
    engine.ingest(_event(data_mode="delayed"), now=NOW)
    result = engine.ingest(
        _event(
            contract="NVDA__260828C00205000",
            at=NOW + timedelta(seconds=10),
            data_mode="delayed",
        ),
        now=NOW + timedelta(seconds=10),
    )
    assert result is not None
    assert result.stage == "BUILDING"
    assert result.evidence_grade in {"B", "C"}
    assert result.actionable is False
    assert "insufficient realtime evidence" in result.reasons


def test_complex_dominance_blocks_confirmation():
    engine = RealtimeFlowEngine()
    engine.ingest(_event(qualifiers=(32,)), now=NOW)
    result = engine.ingest(
        _event(
            contract="NVDA__260828C00205000",
            at=NOW + timedelta(seconds=10),
            qualifiers=(33,),
        ),
        now=NOW + timedelta(seconds=10),
    )
    assert result is not None
    assert result.complex_ratio == 1.0
    assert result.stage == "BUILDING"
    assert result.actionable is False


def test_opposing_flow_can_fail_existing_thesis():
    engine = RealtimeFlowEngine()
    engine.ingest(_event(), now=NOW)
    bullish = engine.ingest(
        _event(
            contract="NVDA__260828C00205000",
            at=NOW + timedelta(seconds=10),
        ),
        now=NOW + timedelta(seconds=10),
    )
    assert bullish is not None and bullish.stage == "CONFIRMED"

    engine.ingest(
        _event(
            contract="NVDA__260828P00195000",
            at=NOW + timedelta(seconds=20),
            premium=900_000,
            sentiment="BEARISH",
            underlying_price=199.9,
        ),
        now=NOW + timedelta(seconds=20),
    )
    refreshed = engine._snapshot("NVDA", BULLISH, NOW + timedelta(seconds=20))
    assert refreshed is not None
    assert refreshed.stage == "FAILED"
    assert refreshed.actionable is False
    assert refreshed.opposing_premium >= 900_000


def test_stale_evidence_is_not_actionable():
    engine = RealtimeFlowEngine(max_event_age_seconds=30)
    engine.ingest(_event(), now=NOW)
    engine.ingest(
        _event(contract="NVDA__260828C00205000", at=NOW + timedelta(seconds=5)),
        now=NOW + timedelta(seconds=5),
    )
    stale = engine._snapshot("NVDA", BULLISH, NOW + timedelta(seconds=60))
    assert stale is not None
    assert stale.stage == "BUILDING"
    assert stale.actionable is False
    assert any(reason.startswith("stale ") for reason in stale.reasons)
