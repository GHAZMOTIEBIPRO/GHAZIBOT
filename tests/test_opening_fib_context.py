"""No licensed prices: official public-source fixtures only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from options_radar.opening_fib_context import (
    collect_official_events, fib_context_lines, render_weekly_official_brief,
)
from options_radar.opening_fib_scan import render_private_digest
from scripts import run_weekly_official_brief as weekly

NOW = datetime(2026, 11, 15, 14, 15, tzinfo=timezone.utc)


def source(tmp_path: Path, name: str, payload: dict, created: datetime | None = None) -> None:
    schemas = {
        "week_agenda": "ghazi.week_agenda.v1",
        "ir_news": "ghazi.ir_news.v1",
        "catalyst_watchlist": "ghazi.catalyst_watchlist.v1",
    }
    data = {"schema": schemas[name], "generated_at": (created or NOW).isoformat(), **payload}
    (tmp_path / (name + ".json")).write_text(json.dumps(data), encoding="utf-8")


def fixture_events(tmp_path: Path) -> None:
    source(tmp_path, "week_agenda", {"items": [
        {"symbol": "NVDA", "kind": "COMPANY_SCHEDULE", "date": "2026-11-17",
         "basis": "COMPANY_ANNOUNCED", "title_ar": "نتائج الربع",
         "source": "Company IR", "source_url": "https://investor.nvidia.com/events/test"},
        {"symbol": "NVDA", "kind": "COMPANY_SCHEDULE", "date": "2026-11-18",
         "basis": "INFERRED", "title": "غير مؤكد",
         "source": "Company IR", "source_url": "https://investor.nvidia.com/events/guessed"},
        {"symbol": "SPY", "date": "2026-11-19", "basis": "COMPANY_ANNOUNCED",
         "title": "تجاهل الرابط غير الآمن", "source": "Company IR", "source_url": "javascript:alert(1)"},
    ]})
    source(tmp_path, "ir_news", {"items": [
        {"symbol": "NVDA", "title": "خبر من الشركة & تفاصيل",
         "source_kind": "press_release", "source_published_at": "2026-11-14T12:00:00+00:00",
         "url": "https://investor.nvidia.com/news/update"},
        {"symbol": "AMD", "title": "خبر قديم لا يظهر",
         "source_kind": "press_release", "source_published_at": "2026-10-10T12:00:00+00:00",
         "url": "https://ir.amd.com/stale"},
    ]})
    source(tmp_path, "catalyst_watchlist", {"status": "AVAILABLE", "events": [
        {"symbol": "NVDA", "source": "SEC EDGAR", "date": "2026-11-14",
         "label": "إفصاح رسمي", "source_url": "https://www.sec.gov/Archives/edgar/data/1/2.htm"},
        {"symbol": "NVDA", "source": "unverified_blog", "date": "2026-11-14",
         "label": "إشاعة", "source_url": "https://example.com/rumor"},
    ]})


def test_source_backed_upcoming_event_and_no_inference(tmp_path):
    fixture_events(tmp_path)
    context = collect_official_events(tmp_path, now=NOW, symbols=["NVDA", "SPY", "AMD"])
    events = context["by_symbol"]["NVDA"]
    assert events[0]["kind"] == "UPCOMING_COMPANY_EVENT"
    assert events[0]["date"] == "2026-11-17"
    assert context["event_count"] == 3
    assert not context["by_symbol"].get("SPY")
    assert not context["by_symbol"].get("AMD")
    assert all("guessed" not in e["url"] and "rumor" not in e["url"] for e in events)


def test_no_stale_or_future_date_context(tmp_path):
    source(tmp_path, "week_agenda", {"items": [
        {"symbol": "NVDA", "date": "2026-11-17", "basis": "COMPANY_ANNOUNCED",
         "source": "Company IR", "title": "Filing", "source_url": "https://ir.example.com/a"}
    ]}, created=NOW - timedelta(days=6))
    ctx = collect_official_events(tmp_path, now=NOW, symbols=["NVDA"])
    assert ctx["sources"]["week_agenda"] == "UNAVAILABLE_OR_STALE"
    assert ctx["event_count"] == 0


def test_official_links_escaped_and_keep_news_separate_from_calls(tmp_path):
    fixture_events(tmp_path)
    context = collect_official_events(tmp_path, now=NOW, symbols=["NVDA"])
    lines = fib_context_lines(context, symbols=["NVDA"])
    msg = "\n".join(lines)
    assert "<a href=\"https://investor.nvidia.com/events/test\">" in msg
    assert "خبر من الشركة &amp; تفاصيل" not in msg or "&amp;" in msg
    assert "لا تحدد اتجاه السعر" in msg
    assert "إشاعة" not in msg


def test_daily_digest_shows_confirmed_upcoming_event_even_without_trade(tmp_path):
    fixture_events(tmp_path)
    context = collect_official_events(tmp_path, now=NOW, symbols=["NVDA", "SPY"])
    message = render_private_digest(
        [{"symbol": "NVDA", "state": "WAIT"}, {"symbol": "SPY", "state": "NO_DATA"}],
        session_date="2026-11-16", official_context=context,
    )
    assert "NVDA" in message
    assert "موعد رسمي مقبل" in message
    assert "مراقبة كول 0" in message
    assert len(message) <= 3900


def test_weekly_report_warns_of_source_coverage_and_not_direction(tmp_path):
    fixture_events(tmp_path)
    context = collect_official_events(tmp_path, now=NOW, symbols=["NVDA"])
    message = render_weekly_official_brief(context, now=NOW)
    assert "2026-11-17" in message
    assert "المواعيد القادمة" in message
    assert "3 من 3" in message
    assert "لا" in message and "توصيات عقود" in message
    assert "https://investor.nvidia.com/events/test" in message


def test_weekly_dry_run_reads_sources_without_bot_credentials(tmp_path, monkeypatch):
    fixture_events(tmp_path)
    universe = tmp_path / "universe.txt"
    universe.write_text("NVDA\nSPY\n", encoding="utf-8")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_OWNER_CHAT_ID", raising=False)
    marker = tmp_path / "state/sent.json"
    result = weekly.run(now=NOW, context_dir=tmp_path, universe=universe,
                        state_path=marker, dry_run=True)
    assert result.startswith("WEEKLY_DRY_RUN_READY_SOURCES_3")
    assert not marker.exists()


def test_weekly_sends_only_private_owner_then_records_date_and_dedupes(tmp_path, monkeypatch):
    fixture_events(tmp_path)
    universe = tmp_path / "universe.txt"
    universe.write_text("NVDA\n", encoding="utf-8")
    marker = tmp_path / "sent.json"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake_credential")
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "654321")
    monkeypatch.delenv("TELEGRAM_OWNER_USERNAME", raising=False)
    sent = []
    monkeypatch.setattr(weekly, "owner_chat", lambda chat_id: {"type": "private"})
    monkeypatch.setattr(weekly, "send_html_message",
                        lambda text, *, chat_id: sent.append((text, chat_id)) or SimpleNamespace(message_id=99))
    assert weekly.run(now=NOW, context_dir=tmp_path, universe=universe,
                      state_path=marker) == "WEEKLY_DELIVERED"
    assert len(sent) == 1 and sent[0][1] == "654321"
    assert json.loads(marker.read_text()) == {"sent_date": "2026-11-15"}
    assert weekly.run(now=NOW, context_dir=tmp_path, universe=universe,
                      state_path=marker) == "SKIP_ALREADY_SENT"
    assert len(sent) == 1


def test_weekly_rejects_group_even_with_valid_chat_id(tmp_path, monkeypatch):
    fixture_events(tmp_path)
    universe = tmp_path / "universe.txt"
    universe.write_text("NVDA\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "-1001234")
    monkeypatch.setattr(weekly, "owner_chat", lambda chat_id: {"type": "supergroup"})
    assert weekly.run(now=NOW, context_dir=tmp_path, universe=universe,
                      state_path=tmp_path / "sent.json") == "WEEKLY_NOT_PRIVATE_CHAT"


def test_weekly_refuses_to_send_when_all_sources_are_stale(tmp_path, monkeypatch):
    universe = tmp_path / "universe.txt"
    universe.write_text("NVDA\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake")
    monkeypatch.setenv("TELEGRAM_OWNER_CHAT_ID", "1234")
    assert weekly.run(now=NOW, context_dir=tmp_path, universe=universe,
                      state_path=tmp_path / "sent.json") == "WEEKLY_OFFICIAL_SOURCES_STALE_OR_MISSING"
