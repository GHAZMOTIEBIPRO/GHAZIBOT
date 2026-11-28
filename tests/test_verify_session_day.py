"""Acceptance judge: delivery times against the windows, UNCONFIRMED shown, early closes from XNYS."""
import json

from scripts import verify_session_day as v


def _write(d, name, body):
    (d / name).write_text(json.dumps(body))


def test_on_time_late_unconfirmed_and_missing(tmp_path):
    d = tmp_path / "2026-11-30"
    d.mkdir()
    ok = {"DELIVERED": "2026-11-30T13:31:10+00:00"}  # 08:31 New York
    _write(d, "report_EARLY.json", {"status": "DELIVERED", "attempt": 1, "messages": 2, "accepted": 2,
                                    "items": {"a": {"status": "DELIVERED", "at": ok["DELIVERED"]},
                                              "b": {"status": "DELIVERED", "at": "2026-11-30T13:33:00+00:00"}}})
    _write(d, "report_FINAL.json", {"status": "DELIVERED", "items": {"a": {"status": "DELIVERED",
                                                                           "at": "2026-11-30T14:41:00+00:00"}}})
    _write(d, "session_OPENING.json", {"status": "UNCONFIRMED", "sent_at": "2026-11-30T15:05:00+00:00"})
    rows = {r["stage"]: r for r in v.judge("2026-11-30", d)}
    assert rows["EARLY"]["verdict"] == "PASS" and "16:31 RUH" in rows["EARLY"]["first_accepted"]
    assert rows["FINAL"]["verdict"] == "LATE"          # 09:41 New York, after the 09:30 deadline
    assert rows["OPENING"]["verdict"] == "UNCONFIRMED"
    assert rows["LASTHOUR"]["verdict"] == rows["POSTCLOSE"]["verdict"] == "MISSING"


def test_early_close_moves_the_windows():
    w = v.windows("2026-11-27")  # day after Thanksgiving: 13:00 close
    assert w["LASTHOUR"][1].astimezone(v.NY).hour == 13 and v.windows("2026-11-28") == {}
