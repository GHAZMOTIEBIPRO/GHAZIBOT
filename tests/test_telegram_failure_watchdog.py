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
    assert "RUN_BRANCH:" in text
    assert "RUN_EVENT:" in text
    assert "python -m scripts.telegram_watchdog_status --send" in text
    from scripts.telegram_watchdog_status import render_message
    message = render_message("failure", {
        "name": "Classical Direction", "conclusion": "failure", "branch": "main",
        "event": "push", "id": "123", "url": "https://github.com/test/repo/actions/runs/123",
    })
    assert "الفرع:" in message
    assert "نوع التشغيل:" in message


def test_watchdog_recovery_only_for_classical_success_and_main():
    text = Path(".github/workflows/telegram-failure-watchdog.yml").read_text(encoding="utf-8")
    assert "github.event.workflow_run.name == 'BLACK BOX Omega Classical Direction Radar'" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "steps.classify.outputs.notify == 'true'" in text
    assert "WATCHDOG_KIND:" in text
