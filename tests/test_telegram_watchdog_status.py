import requests

from scripts.telegram_watchdog_status import (
    classify_transition,
    fetch_completed_runs,
    render_message,
)

WORKFLOW_ID = 100


def _run(run_id, conclusion, *, workflow=WORKFLOW_ID, branch="main", status="completed"):
    return {
        "id": run_id,
        "workflow_id": workflow,
        "head_branch": branch,
        "conclusion": conclusion,
        "status": status,
    }


def _classify(run_id, conclusion, history, *, branch="main"):
    return classify_transition(
        run_id=run_id, workflow_id=WORKFLOW_ID, conclusion=conclusion,
        branch=branch, history=history,
    )


def test_first_main_failure_notifies():
    assert _classify(11, "failure", [_run(11, "failure"), _run(10, "success")]) == ("failure", None)


def test_consecutive_failures_notify_only_once():
    assert _classify(12, "failure", [_run(12, "failure"), _run(11, "failure")]) == ("ignore", None)


def test_success_after_failure_reports_recovery_once():
    rows = [_run(12, "success"), _run(11, "failure"), _run(10, "success")]
    assert _classify(12, "success", rows) == ("recovery", 11)
    assert _classify(13, "success", [_run(13, "success"), *rows]) == ("ignore", None)


def test_late_failure_event_does_not_alarm_after_newer_success():
    rows = [_run(12, "success"), _run(11, "failure")]
    assert _classify(11, "failure", rows) == ("ignore", None)


def test_out_of_order_recovery_does_not_repeat():
    rows = [_run(14, "success"), _run(13, "success"), _run(12, "failure")]
    assert _classify(13, "success", rows) == ("ignore", None)


def test_timed_out_and_action_required_are_failures():
    for status in ("timed_out", "action_required", "startup_failure"):
        rows = [_run(11, status), _run(10, "success")]
        assert _classify(11, status, rows) == ("failure", None)


def test_cancelled_and_pr_branches_do_not_notify():
    assert _classify(11, "cancelled", [_run(11, "cancelled")]) == ("ignore", None)
    assert _classify(11, "failure", [_run(11, "failure", branch="feature")], branch="feature") == ("ignore", None)


def test_untrusted_wrong_workflow_does_not_trigger_recovery():
    rows = [_run(12, "success"), _run(11, "failure", workflow=500)]
    assert _classify(12, "success", rows) == ("ignore", None)


def test_missing_api_history_retains_failures_but_never_invents_recovery():
    assert _classify(11, "failure", None) == ("failure", None)
    assert _classify(12, "success", None) == ("ignore", None)


def test_run_absent_from_bounded_history_not_reported_as_current():
    assert _classify(10, "failure", [_run(60, "success")]) == ("ignore", None)


def test_manual_watchdog_check():
    assert classify_transition(
        run_id=0, workflow_id=0, conclusion="manual", branch="manual", history=None, manual=True
    ) == ("manual", None)


def test_render_message_escapes_untrusted_github_names():
    event = {
        "name": "<script>demo</script>", "conclusion": "failure",
        "branch": "main", "event": "push", "id": "38503050189",
        "url": "https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/runs/38503050189",
    }
    message = render_message("failure", event)
    assert "<script>" not in message
    assert "&lt;script&gt;" in message
    assert "فشل تشغيل Omega" in message
    assert "الفرع:" in message and "نوع التشغيل:" in message
    recovered = render_message("recovery", event, 38503050189)
    assert "تعافي تشغيل Omega" in recovered
    assert "نجاح الفحص لا يثبت وصول توصيات Telegram" in recovered


def test_history_api_reads_single_workflow_main_completed(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"workflow_runs": [_run(12, "success"), _run(11, "failure")]}

    def fake_get(url, *, headers, params, timeout):
        assert url.endswith("/actions/workflows/100/runs")
        assert headers["Authorization"] == "Bearer token"
        assert params == {"branch": "main", "status": "completed", "per_page": 50}
        assert timeout <= 20
        return Response()

    monkeypatch.setattr("scripts.telegram_watchdog_status.requests.get", fake_get)
    assert len(fetch_completed_runs(
        repository="GHAZMOTIEBIPRO/GHAZIBOT", workflow_id=WORKFLOW_ID, token="token"
    )) == 2


def test_history_api_failure_does_not_create_false_recovery(monkeypatch):
    def bad_get(*args, **kwargs):
        raise requests.Timeout("provider unavailable")

    monkeypatch.setattr("scripts.telegram_watchdog_status.requests.get", bad_get)
    assert fetch_completed_runs(repository="o/r", workflow_id=WORKFLOW_ID, token="token") is None
