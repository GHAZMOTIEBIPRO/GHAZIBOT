from datetime import datetime, timedelta, timezone

import scripts.send_independent_path_alerts as sender


class TelegramReceipt:
    message_id = 991


def _fresh_payload(*, now=None):
    current = now or datetime.now(timezone.utc)
    return {
        "path": "stocks",
        "architecture": "independent_stock_radar_v1",
        "independent_from_options_radar": True,
        "generated_at": current.isoformat(),
        "source_fast_scan_generated_at": (current - timedelta(minutes=5)).isoformat(),
        "summary": {
            "market_rows_seen": 7019,
            "fast_actionable": 1,
            "stocks_deep_validated": 1,
            "official_causes": 0,
        },
        "stocks": [{
            "symbol": "XYZ", "stage": "RESEARCH_ONLY", "alert_stage": "NONE", "score": 50,
        }],
    }


def test_one_fresh_no_signal_full_market_scan_reports_truth_once(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", lambda message: sent.append(message) or TelegramReceipt())
    monkeypatch.setenv("STOCK_WATCH_MIN_SCORE", "62")
    payload = _fresh_payload()
    state = {"sent": {}}
    assert sender.send_stocks(payload, state) == 0
    assert state["last_eligible_count"] == 0
    assert state["last_filtered_count"] == 1
    assert state["last_status_sent"] is True
    assert len(sent) == 1
    assert "7,019" in sent[0]
    assert "ليست توصية شراء" in sent[0]
    assert "الإشارات الجديدة المؤهلة: <b>0</b>" in sent[0]
    assert sender.send_stocks(payload, state) == 0
    assert state["last_status_sent"] is False
    assert len(sent) == 1


def test_no_daily_report_from_stale_or_unverifiable_scan(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", lambda text: sent.append(text) or TelegramReceipt())
    now = datetime.now(timezone.utc)
    cases = []
    payload = _fresh_payload(now=now)
    payload["source_fast_scan_generated_at"] = (now - timedelta(hours=2)).isoformat()
    cases.append(payload)
    payload = _fresh_payload(now=now)
    payload["generated_at"] = (now - timedelta(hours=2)).isoformat()
    cases.append(payload)
    payload = _fresh_payload(now=now)
    payload["source_fast_scan_generated_at"] = "2026-10-15T16:00:00"
    cases.append(payload)
    payload = _fresh_payload(now=now)
    payload["summary"]["market_rows_seen"] = 0
    cases.append(payload)
    payload = _fresh_payload(now=now)
    payload["architecture"] = "untrusted"
    cases.append(payload)
    for item in cases:
        state = {"sent": {}}
        assert sender.send_stocks(item, state) == 0
        assert state["last_status_sent"] is False
    assert sent == []


def test_daily_status_never_displaces_eligible_watch(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", lambda msg: sent.append(msg) or TelegramReceipt())
    monkeypatch.setenv("STOCK_WATCH_MIN_SCORE", "62")
    payload = _fresh_payload()
    payload["stocks"] = [{
        "symbol": "XYZ", "stage": "PRESSURE_BUILDING",
        "alert_stage": "WATCH", "score": 66,
    }]
    state = {"sent": {}}
    assert sender.send_stocks(payload, state) == 1
    assert state["last_eligible_count"] == 1
    assert state["last_status_sent"] is False
    assert len(sent) == 1
    assert "WATCH" in sent[0]


def test_deduplicated_opportunity_remains_not_a_new_one(monkeypatch):
    sent = []
    monkeypatch.setattr(sender, "_send", lambda msg: sent.append(msg) or TelegramReceipt())
    monkeypatch.setenv("STOCK_WATCH_MIN_SCORE", "62")
    payload = _fresh_payload()
    payload["stocks"] = [{
        "symbol": "XYZ", "stage": "PRESSURE_BUILDING",
        "alert_stage": "WATCH", "score": 66,
    }]
    state = {"sent": {}}
    assert sender.send_stocks(payload, state) == 1
    assert sender.send_stocks(payload, state) == 0
    assert state["last_duplicate_count"] == 1
    assert len(sent) == 1
