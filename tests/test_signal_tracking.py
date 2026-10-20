import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from options_radar.signal_tracking import PER_SYMBOL, build

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def rec(symbol, t, status, stage="PRESSURE_BUILDING"):
    return {"symbol": symbol, "signal_time": t, "entry_stage": stage, "entry_price": 3.2,
            "follow_through_target_pct": 8.0, "failure_threshold_pct": 5.0, "audit_status": status,
            "audit_mfe_pct": 9.1, "audit_mae_pct": -2.0, "signal_session_valid": True}


def test_recent_signals_newest_first_with_audited_status_and_totals():
    rows = [rec("RGC", f"2026-10-{d:02d}T14:00:00+00:00", s)
            for d, s in [(1, "success"), (2, "failed"), (3, "pending"), (4, "failed"),
                         (5, "non_decisive"), (6, "success"), (7, "pending")]]
    rows.append({**rec("RGC", "2026-10-08T14:00:00+00:00", "success"), "signal_session_valid": False})
    rows.append(rec("<b>", "2026-10-08T14:00:00+00:00", "success"))
    out = build({"records": {str(i): r for i, r in enumerate(rows)}}, now=NOW)
    rgc = out["symbols"]["RGC"]
    assert list(out["symbols"]) == ["RGC"]  # invalid session and unsafe symbol excluded
    assert len(rgc["recent"]) == PER_SYMBOL
    assert rgc["recent"][0]["signal_time"].startswith("2026-10-07")
    assert rgc["recent"][1]["status_ar"] == "بلغ الهدف قبل الوقف"
    assert rgc["totals"] == {"signals": 7, "decisive": 4, "target_first": 2, "stop_first": 2, "pending": 2}
    assert out["is_win_probability"] is False


def test_cli_runs_without_third_party_packages(tmp_path):
    audit = tmp_path / "a.json"
    audit.write_text(json.dumps({"records": {"1": rec("AAA", "2026-10-01T14:00:00+00:00", "success")}}))
    blocker = tmp_path / "block"
    blocker.mkdir()
    for name in ("pandas", "numpy"):
        (blocker / f"{name}.py").write_text("raise ImportError('blocked')\n")
    out = tmp_path / "o.json"
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-m", "scripts.run_signal_tracking", "--audit", str(audit),
                             "--output", str(out)], cwd=root, env={"PYTHONPATH": str(blocker), "PATH": "/usr/bin:/bin"},
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text())["symbols"]["AAA"]["totals"]["target_first"] == 1
