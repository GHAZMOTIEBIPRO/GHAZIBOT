import json
import sys
from datetime import datetime, timedelta, timezone

import scripts.send_independent_path_alerts as sender
from scripts.send_independent_path_alerts import _stock_message, _stock_payload_fresh

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
ROW = {"symbol": "RGC", "score": 71, "price": 3.2, "move_pct": 12.0, "stage": "PRESSURE_BUILDING",
       "relative_volume": 3.4, "time_normalized_rvol": {"available": True, "ratio": 2.1},
       "cause": {"status": "OFFICIAL", "status_ar": "إفصاح رسمي", "headline": "8-K material agreement"}}


def test_alert_has_direction_catalyst_volume_levels_time_and_link():
    text = _stock_message(ROW, "2026-10-20T14:52:10+00:00")
    assert "مراقبة صعود بحثية" in text
    assert "8-K material agreement" in text
    assert "RVOL بنفس الوقت <b>2.1×</b>" in text and "متوسط يوم كامل <b>3.4×</b>" in text
    assert "هدف <b>$3.46</b> (+8%)" in text and "إبطال <b>$3.04</b> (−5%)" in text
    assert "وقت المسح: 2026-10-20 14:52:10 UTC" in text
    assert "دون نقطة التعادل" in text
    assert '<a href="https://ghazibot.vercel.app/?chart=RGC">' in text


def test_missing_volume_is_shown_as_unavailable_not_zero():
    text = _stock_message({**ROW, "relative_volume": None, "time_normalized_rvol": {"available": False}})
    assert "RVOL بنفس الوقت غير متاح" in text and "متوسط يوم كامل غير متاح" in text
    assert "وقت المسح" not in text  # no observation time, no invented time


def test_payload_freshness_gate():
    assert _stock_payload_fresh({"generated_at": (NOW - timedelta(minutes=10)).isoformat()}, now=NOW)
    assert not _stock_payload_fresh({"generated_at": (NOW - timedelta(minutes=41)).isoformat()}, now=NOW)
    assert not _stock_payload_fresh({"generated_at": (NOW + timedelta(minutes=10)).isoformat()}, now=NOW)
    assert not _stock_payload_fresh({"generated_at": "2026-10-20T14:50:00"}, now=NOW)  # naive
    assert not _stock_payload_fresh({}, now=NOW)


def test_cli_sends_nothing_for_a_stale_scan(tmp_path, monkeypatch):
    payload = tmp_path / "p.json"
    payload.write_text(json.dumps({"path": "stocks", "generated_at": "2026-01-01T00:00:00+00:00",
                                   "stocks": [ROW]}))
    state = tmp_path / "s.json"
    monkeypatch.setattr(sender, "_send", lambda text: (_ for _ in ()).throw(AssertionError("must not send")))
    monkeypatch.setattr(sys, "argv", ["x", "--path", "stocks", "--payload", str(payload), "--state", str(state)])
    sender.main()
    saved = json.loads(state.read_text())
    assert saved["last_suppressed_stale_scan"]["generated_at"] == "2026-01-01T00:00:00+00:00"
    assert saved.get("sent", {}) == {}
