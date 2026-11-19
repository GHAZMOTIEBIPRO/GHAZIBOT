"""Historical replay of the fixed opening-Fibonacci rule: split, statistics, privacy and gates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from scripts import run_opening_fib_history as hist

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 19, 22, 0, tzinfo=timezone.utc)


def test_sessions_are_completed_xnys_days_including_early_closes_and_never_today_open():
    sessions = hist.completed_sessions(NOW, 60)
    assert len(sessions) == 60
    labels = [s[0] for s in sessions]
    assert labels == sorted(labels) and labels[-1] == "2026-11-19"  # closed 21:00Z, 16 min passed
    assert "2026-11-27" not in labels  # Thanksgiving is in the future here; holidays never appear
    assert all(close + timedelta(minutes=16) <= NOW for _, _, close in sessions)
    early = hist.completed_sessions(datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc), 5)
    assert early[-1][0] == "2026-11-18"  # today's session is not complete yet


def test_split_statistics_and_the_both_halves_rule():
    sessions = [(f"2026-10-{d:02d}", None, None) for d in range(1, 11)]
    rows = ([(i, "WIN", 1.5) for i in range(5) for _ in range(4)] + [(i, "LOSS", -1.0) for i in range(5) for _ in range(3)]
            + [(i, "WIN", 1.4) for i in range(5, 10) for _ in range(3)] + [(i, "LOSS", -1.0) for i in range(5, 10) for _ in range(4)]
            + [(0, "NO_TRADE", None)])
    s = hist.summarize({"rows": rows, "counts": {"NO_TRADE": 1}, "fetch_failures": 0}, sessions)
    first, later = s["first"], s["holdout"]
    assert (first["decisions"], first["wins"], later["decisions"], later["wins"]) == (35, 20, 35, 15)
    assert abs(first["mean_r"] - (20 * 1.5 - 15) / 35) < 1e-12
    assert first["win_ci95"][0] < first["win_rate"] < first["win_ci95"][1]
    assert s["first_range"] == ("2026-10-01", "2026-10-05") and s["holdout_range"] == ("2026-10-06", "2026-10-10")
    # the holdout mean R is (15*1.4 - 20)/35 > 0 and the first half's is > 0 -> both positive
    assert s["mean_r_positive_in_both_halves"] is True
    small = hist.summarize({"rows": rows[:10], "counts": {}, "fetch_failures": 0}, sessions)
    assert small["mean_r_positive_in_both_halves"] is False  # below 30 per half: no conclusion


def test_message_is_arabic_rtl_private_and_carries_no_ticker():
    sessions = [(f"2026-10-{d:02d}", None, None) for d in range(1, 5)]
    rows = [(0, "WIN", 1.6), (2, "LOSS", -1.02)]
    text = hist.render_message(hist.summarize({"rows": rows, "counts": {"WIN": 1, "LOSS": 1}, "fetch_failures": 0},
                                              sessions))
    assert "ليست أداء عقود خيارات" in text and "لم تُعدَّل أي معلمة" in text
    assert "العينة أقل من 30" in text and "لا أفضلية مثبتة" in text
    assert "AAPL" not in text and "NVDA" not in text and len(text) <= 4096


class _Provider:
    rights_source = "alpaca_sip"

    def __init__(self, env, now):
        self.env = env

    def status(self):
        return "READY" if self.env.get("ALPACA_API_KEY") else "CREDENTIALS_MISSING"

    def multi_bars(self, symbols, timeframe, start, end, batch=70):
        return {"status": "OK", "bars": {}, "feed": {}, "failed_batches": 0}


def test_gates_fail_closed_and_dry_run_never_sends(tmp_path, monkeypatch):
    universe = tmp_path / "u.txt"
    universe.write_text("SPY\nQQQ\n", encoding="utf-8")
    assert hist.run(now=NOW, universe=universe, sessions=5, dry_run=True, provider_factory=_Provider,
                    env={}) == "HISTORY_PROVIDER_UNAVAILABLE"
    denied = {"ALPACA_API_KEY": "k", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "false"}
    assert hist.run(now=NOW, universe=universe, sessions=5, dry_run=True, provider_factory=_Provider,
                    env=denied) == "HISTORY_PRIVATE_RIGHTS_NOT_AUTHORIZED"
    monkeypatch.setattr(hist, "deliver_private", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    monkeypatch.setattr(hist, "decide", lambda *a, **k: type("D", (), {"allowed": True})())
    monkeypatch.setattr(hist, "replay_sessions", lambda *a, **k: {"rows": [(0, "WIN", 1.0)], "counts": {},
                                                                    "fetch_failures": 0})
    assert hist.run(now=NOW, universe=universe, sessions=5, dry_run=True, provider_factory=_Provider,
                    env={"ALPACA_API_KEY": "k"}) == "HISTORY_DRY_RUN_COMPUTED"


def test_workflow_is_manual_read_only_and_never_commits():
    text = (ROOT / ".github/workflows/opening-fib-history.yml").read_text(encoding="utf-8")
    spec = yaml.safe_load(text)
    assert set(spec[True]) == {"workflow_dispatch"} and spec[True]["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True
    assert spec["permissions"] == {"contents": "read"}
    assert "git push" not in text and "upload-artifact" not in text
    assert "${{ inputs.sessions }}" not in spec["jobs"]["replay"]["steps"][-1]["run"]  # passed via env
