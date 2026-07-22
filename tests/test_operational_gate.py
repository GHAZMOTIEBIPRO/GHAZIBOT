from __future__ import annotations

import json
from pathlib import Path

from options_radar.calibration_report import render_calibration_markdown
from options_radar.operations import build_operational_status
from options_radar.settings import Settings
from scripts.calibration_gate import evaluate, mark


def test_operational_status_never_exposes_secret_values(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "super-secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "email-secret")
    monkeypatch.setenv("REPORT_EMAIL_TO", "to@example.com")
    settings = Settings()

    status = build_operational_status(settings)
    serialized = json.dumps(status)

    assert status["live_alert_channel_ready"] is True
    assert status["daily_report_ready"] is True
    assert "super-secret-token" not in serialized
    assert "email-secret" not in serialized


def test_calibration_markdown_opens_review_not_auto_changes() -> None:
    report = {
        "calibration_ready": True,
        "priced_sample": 100,
        "minimum_sample": 100,
        "decision": "Eligible for score recalibration review",
        "score_bands": [],
        "catalysts": [],
    }
    markdown = render_calibration_markdown(report, "2026.07-phase2")
    assert "READY FOR INDEPENDENT REVIEW" in markdown
    assert "does not authorize automatic score changes" in markdown


def test_calibration_gate_is_one_time(tmp_path: Path, monkeypatch) -> None:
    calibration = tmp_path / "calibration.json"
    marker = tmp_path / "marker.json"
    output = tmp_path / "output.txt"
    calibration.write_text(
        json.dumps({"calibration_ready": True, "priced_sample": 100, "minimum_sample": 100}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert evaluate(calibration, marker) == 0
    first = output.read_text(encoding="utf-8")
    assert "should_open=true" in first

    assert mark(marker, "https://github.com/example/repo/issues/1") == 0
    output.write_text("", encoding="utf-8")
    assert evaluate(calibration, marker) == 0
    second = output.read_text(encoding="utf-8")
    assert "should_open=false" in second
