from pathlib import Path


def test_failure_watchdog_ignores_cancelled_and_non_main_runs():
    text = Path(".github/workflows/telegram-failure-watchdog.yml").read_text(encoding="utf-8")
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert "github.event.workflow_run.conclusion == 'cancelled'" not in text


def test_failure_watchdog_keeps_real_failure_states():
    text = Path(".github/workflows/telegram-failure-watchdog.yml").read_text(encoding="utf-8")
    for conclusion in ("failure", "timed_out", "action_required", "startup_failure"):
        assert f"github.event.workflow_run.conclusion == '{conclusion}'" in text


def test_failure_alert_includes_branch_and_event_context():
    text = Path(".github/workflows/telegram-failure-watchdog.yml").read_text(encoding="utf-8")
    assert "RUN_BRANCH:" in text
    assert "RUN_EVENT:" in text
    assert "الفرع:" in text
    assert "نوع التشغيل:" in text
