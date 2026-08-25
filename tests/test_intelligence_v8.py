from __future__ import annotations

from datetime import datetime, timedelta, timezone

from options_radar.flow_memory import attach_strike_clusters, update_flow_memory
from options_radar.intelligence_grading import grade_alerts, register_alert
from scripts.send_options_intelligence_v8 import _eligible_v8


def _contract(*, strike: float = 100.0, volume: int = 1000, oi: int = 400) -> dict:
    return {
        "symbol": "XYZ",
        "contract_symbol": f"XYZ260828C{int(strike * 1000):08d}",
        "option_type": "call",
        "direction": "CALL",
        "expiration": "2026-08-28",
        "strike": strike,
        "underlying_price": 100.0,
        "bid": 1.90,
        "ask": 2.10,
        "mid": 2.00,
        "volume": volume,
        "open_interest": oi,
        "vol_oi": volume / oi,
        "score": 90,
        "strict_score": 90,
        "signal_grade": "A+",
        "flow_momentum_score": 82,
        "flow_evidence": {"execution_pressure_proxy": "ask"},
    }


def test_repeat_flow_memory_uses_incremental_volume() -> None:
    state: dict = {}
    t0 = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)
    first = update_flow_memory(state, [_contract(volume=1000)], now=t0)[0]
    assert first["flow_volume_delta"] == 0
    assert first["repeat_flow_hits"] == 0

    second = update_flow_memory(
        state,
        [_contract(volume=1300)],
        now=t0 + timedelta(minutes=10),
    )[0]
    assert second["flow_volume_delta"] == 300
    assert second["flow_notional_delta_proxy"] == 60_000
    assert second["repeat_flow_hits"] == 1

    third = update_flow_memory(
        state,
        [_contract(volume=1700)],
        now=t0 + timedelta(minutes=20),
    )[0]
    assert third["repeat_flow_hits"] == 2
    assert third["repeat_flow_confirmed"] is True


def test_strike_clustering_requires_multiple_nearby_strikes() -> None:
    selected = [_contract(strike=100, volume=1200)]
    universe = [
        _contract(strike=97.5, volume=900),
        _contract(strike=100, volume=1200),
        _contract(strike=102.5, volume=850),
        _contract(strike=120, volume=5000),
    ]
    row = attach_strike_clusters(selected, universe)[0]
    assert row["strike_cluster_count"] == 3
    assert row["strike_cluster_confirmed"] is True
    assert 120.0 not in row["strike_cluster_strikes"]


def test_self_grading_tracks_direction_and_option_mark() -> None:
    state: dict = {}
    sent_at = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)
    register_alert(
        state,
        alert_id="alert-1",
        kind="options",
        symbol="XYZ",
        direction="CALL",
        baseline_underlying=100.0,
        baseline_instrument=2.0,
        instrument_key="contract-1",
        sent_at=sent_at,
    )
    scorecard = grade_alerts(
        state,
        underlying_prices={"XYZ": 102.0},
        instrument_prices={"contract-1": 2.6},
        now=sent_at + timedelta(minutes=65),
    )
    checkpoints = state["outcomes"]["alert-1"]["checkpoints"]
    assert checkpoints["15m"]["direction_correct"] is True
    assert checkpoints["60m"]["instrument_return_pct"] == 30.0
    assert scorecard["horizons"]["60m"]["direction_hit_rate"] == 1.0


def test_v8_can_promote_repeated_clustered_snapshot_only_with_catalyst() -> None:
    row = _contract()
    row.update(
        {
            "repeat_flow_confirmed": True,
            "flow_acceleration_strong": True,
            "strike_cluster_confirmed": True,
        }
    )
    flow = {"tier": "SNAPSHOT_PROXY", "score": 80}
    catalyst = {"score": 18, "headline": "Material positive event"}
    assert _eligible_v8(row, catalyst, flow) is True
    assert _eligible_v8(row, None, flow) is False
