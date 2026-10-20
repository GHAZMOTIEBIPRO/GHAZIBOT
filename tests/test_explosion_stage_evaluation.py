from datetime import datetime, timezone

import pytest

from options_radar.explosion_stage_evaluation import evaluate, round_trip_cost_pct, wilson
from options_radar.signal_features import entry_features, session_phase

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def rec(stage, status, session, *, target=8.0, stop=5.0, price=5.0, mfe=None, mae=None):
    return {"entry_stage": stage, "audit_status": status, "signal_session_date": session,
            "signal_session_valid": True, "follow_through_target_pct": target,
            "failure_threshold_pct": stop, "entry_price": price,
            "audit_mfe_pct": mfe, "audit_mae_pct": mae}


def audit_of(rows):
    return {"records": {str(i): r for i, r in enumerate(rows)}}


def test_precision_breakeven_expectancy_and_recall_use_each_records_own_thresholds():
    rows = ([rec("PRESSURE_BUILDING", "success", "2026-09-01")] * 3
            + [rec("PRESSURE_BUILDING", "failed", "2026-09-02")] * 7
            + [rec("EXPLOSION", "success", "2026-09-03", target=6, stop=6, price=20)] * 5
            + [rec("EXPLOSION", "failed", "2026-09-04", target=6, stop=6, price=20)] * 5)
    out = evaluate(audit_of(rows), now=NOW)
    pb, ex = out["stages"]["PRESSURE_BUILDING"], out["stages"]["EXPLOSION"]
    assert out["population"]["pooled_direction_baseline"] == 0.4
    assert pb["precision_direction"] == 0.3 and pb["lift_vs_pooled_baseline"] == -0.1
    assert pb["breakeven_hit_rate"] == round(5 / 13, 4)
    assert pb["expectancy_gross_pct"] == round((3 * 8 - 7 * 5) / 10, 3)
    assert pb["expectancy_net_pct"] == round((3 * 8 - 7 * 5) / 10 - 0.6, 3)
    assert ex["breakeven_hit_rate"] == 0.5 and ex["expectancy_gross_pct"] == 0.0
    assert ex["expectancy_net_pct"] == -0.2
    assert pb["recall_share_of_all_successes"] == 0.375  # 3 of 8 successes
    assert out["decision_authority"] is False and out["live_rules_changed"] is False


def test_big_move_any_direction_is_reported_separately_from_direction():
    rows = [rec("EXPLOSION", "failed", "2026-09-01", target=6, stop=6, mfe=1.0, mae=-9.0),
            rec("EXPLOSION", "failed", "2026-09-01", target=6, stop=6, mfe=2.0, mae=-7.0)]
    stage = evaluate(audit_of(rows), now=NOW)["stages"]["EXPLOSION"]
    assert stage["precision_direction"] == 0.0
    assert stage["big_move_any_direction_rate"] == 1.0  # volatile, but direction was wrong


def test_time_split_uses_session_order_and_pending_is_not_decisive():
    rows = [rec("PRESSURE_BUILDING", "success", f"2026-09-{d:02d}") for d in range(1, 7)]
    rows += [rec("PRESSURE_BUILDING", "failed", f"2026-09-{d:02d}") for d in range(7, 11)]
    rows += [rec("PRESSURE_BUILDING", "pending", "2026-09-10")]
    split = evaluate(audit_of(rows), now=NOW)["stages"]["PRESSURE_BUILDING"]
    assert split["time_split"]["early_sessions_before"] == "2026-09-07"
    assert split["time_split"]["early"]["precision_direction"] == 1.0
    assert split["time_split"]["late"]["precision_direction"] == 0.0
    assert split["pending"] == 1 and split["decisive"] == 10


def test_invalid_session_and_unknown_stage_are_excluded():
    rows = [rec("PRESSURE_BUILDING", "success", "2026-09-01"),
            {**rec("PRESSURE_BUILDING", "failed", "2026-09-01"), "signal_session_valid": False},
            rec("WATCH", "failed", "2026-09-01")]
    assert evaluate(audit_of(rows), now=NOW)["population"]["decisive"] == 1


def test_cost_model_and_wilson():
    assert round_trip_cost_pct(1.0) == 1.5 and round_trip_cost_pct(5) == 0.6
    assert round_trip_cost_pct(50) == 0.2 and round_trip_cost_pct(None) == 1.5
    low, high = wilson(5, 10)
    assert low < 0.5 < high
    assert wilson(0, 0) is None


def test_entry_features_freeze_present_values_and_keep_missing_none():
    row = {"price": 3.0, "volume": 1_000_000, "relative_volume": 2.5, "float_shares": 9e6,
           "move_pct": 12.0, "sector_vs_market": 1.2, "dilution_risk": 40, "market_regime": "risk_on",
           "cause": {"category": "OFFERING", "official_confirmed": True,
                     "published_at": "2026-10-20T14:30:00+00:00"},
           "institutional_memory": {"acceleration": 55, "earlyness": 60}}
    f = entry_features(row, NOW)
    assert f["version"] == "ENTRY_FEATURES_V1" and f["session_phase"] == "REGULAR"
    assert f["liquidity"]["dollar_volume"] == 3_000_000
    assert f["catalyst"]["age_minutes"] == 30.0 and f["catalyst"]["official"] is True
    assert f["premarket"]["gap_pct"] is None and f["float"]["shares_outstanding"] is None
    assert f["decision_authority"] is False


def test_future_catalyst_time_is_not_freshness():
    row = {"cause": {"published_at": "2026-10-20T16:00:00+00:00"}}
    assert entry_features(row, NOW)["catalyst"]["age_minutes"] is None


def test_evaluator_runs_without_third_party_packages(tmp_path):
    """The walk-forward workflow installs nothing; the CLI must not import
    pandas/numpy directly or through the options_radar package."""
    import ast
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "options_radar/explosion_stage_evaluation.py").read_text(encoding="utf-8"))
    imported = {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert imported <= {"__future__", "math", "collections", "datetime", "typing"}
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"records": {"a": rec("EXPLOSION", "success", "2026-09-01")}}))
    out = tmp_path / "out.json"
    blocker = tmp_path / "block"
    blocker.mkdir()
    for name in ("pandas", "numpy"):
        (blocker / f"{name}.py").write_text("raise ImportError('blocked for test')\n")
    env = {"PYTHONPATH": str(blocker), "PATH": "/usr/bin:/bin"}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.run_explosion_stage_evaluation",
         "--audit", str(audit), "--output", str(out)],
        cwd=root, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text())["population"]["decisive"] == 1


@pytest.mark.parametrize("stamp,phase", [
    (datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc), "PRE_MARKET"),
    (datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc), "REGULAR"),
    (datetime(2026, 10, 20, 21, 0, tzinfo=timezone.utc), "AFTER_HOURS"),
    (datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc), "CLOSED"),
])
def test_session_phase(stamp, phase):
    assert session_phase(stamp) == phase
