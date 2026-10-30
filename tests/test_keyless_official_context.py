"""No-key official CFTC/Treasury/company-IR Telegram briefing tests."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts import send_keyless_official_context as brief

NOW = datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)


def documents(now=NOW):
    stamp = (now - timedelta(minutes=12)).isoformat()
    return (
        {"schema": "ghazi.public_macro.v1", "generated_at": stamp,
         "execution_authority": False,
         "cftc_index_futures": {
             "ES": {"available": True, "positions_as_of": "2026-10-20",
                    "categories": {
                        "leveraged_funds": {"net": -50000, "weekly_change": 10000},
                        "asset_manager": {"net": 80000}}},
             "NQ": {"available": True, "positions_as_of": "2026-10-20",
                    "categories": {
                        "leveraged_funds": {"net": 12000, "weekly_change": -1000},
                        "asset_manager": {"net": 6000}}},
         },
         "treasury_curve": {"available": True, "curve_date": "2026-10-29",
                            "yields_pct": {"10Y": 4.05, "2Y": 3.71}}},
        {"schema": "ghazi.ir_news.v1", "generated_at": stamp,
         "sources": [
             {"symbol": "NVDA", "status": "OK"},
             {"symbol": "AMD", "status": "OK"},
             {"symbol": "META", "status": "ROBOTS_HTTP_403"}],
         "items": [
             {"symbol": "NVDA", "title": "NVIDIA earnings presentation on 11/17",
              "url": "https://investor.nvidia.com/events", "event_at": "2026-11-17",
              "source_published_at": (now-timedelta(days=1)).isoformat()},
             {"symbol": "AMD", "title": "AMD quarterly results",
              "url": "https://ir.amd.com/news", "source_published_at": now.isoformat()},
             {"symbol": "META", "title": "Unverified META event",
              "url": "https://investor.nvidia.com/events",
              "source_published_at": now.isoformat()},
         ]},
    )


def test_real_official_macro_and_ir_compose_single_research_digest():
    macro, ir = documents()
    msg = brief.build_message(macro, ir, now=NOW)
    assert msg and "CFTC" in msg
    assert "Nasdaq-100" in msg and "S&P 500" in msg
    assert "الخزانة" in msg
    assert "NVDA" in msg and "AMD" in msg
    assert "META" not in msg
    assert "2026-10-20" in msg and "2026-11-17" in msg
    assert "ولا توصية CALL/PUT" in msg
    assert "10,000" in msg
    assert 'href="https://investor.nvidia.com/events"' in msg


def test_no_source_cannot_generate_pretext_news_or_fabricated_trade():
    assert brief.build_message({}, {}, now=NOW) is None
    macro, ir = documents()
    old = (NOW - timedelta(hours=96)).isoformat()
    macro["generated_at"] = old
    ir["generated_at"] = old
    assert brief.build_message(macro, ir, now=NOW) is None


def test_one_telegram_send_per_riyadh_day_after_positive_receipt():
    state = {}
    seen = []
    macro, ir = documents()
    def send(msg):
        seen.append(msg)
        return SimpleNamespace(message_id=9183)
    assert brief.deliver(macro, ir, state, now=NOW, send=send) == "TELEGRAM_ACCEPTED"
    assert state["last_message_id"] == 9183
    assert brief.deliver(macro, ir, state, now=NOW + timedelta(minutes=2), send=send) == "NOT_DUE"
    assert len(seen) == 1


def test_weekend_before_riyadh_0815_and_missing_receipt():
    macro, ir = documents()
    assert brief.deliver(macro, ir, {}, now=datetime(2026, 10, 30, 4, 0, tzinfo=timezone.utc),
                         send=lambda _: None) == "NOT_DUE"
    assert brief.deliver(macro, ir, {}, now=datetime(2026, 10, 31, 8, 0, tzinfo=timezone.utc),
                         send=lambda _: None) == "NOT_DUE"
    state = {}
    assert brief.deliver(macro, ir, state, now=NOW,
                         send=lambda _: SimpleNamespace(message_id=None)) == "TELEGRAM_UNCONFIRMED"
    assert state == {}


def test_future_cftc_dates_and_old_issuer_not_paraded_as_current():
    macro, ir = documents()
    macro["cftc_index_futures"]["ES"]["positions_as_of"] = "2026-11-17"
    ir["items"][0]["source_published_at"] = "2026-09-01T01:00:00+00:00"
    text = brief.build_message(macro, ir, now=NOW)
    assert text and "CFTC S&P 500" not in text
    assert "NVIDIA earnings" not in text
    assert "CFTC Nasdaq-100" in text


def test_html_escapes_issuer_text_and_denies_untrusted_host():
    macro, ir = documents()
    ir["items"][0]["title"] = '<script>alert("X")</script> results'
    ir["items"][1]["url"] = "https://evil.example.com/price"
    msg = brief.build_message(macro, ir, now=NOW)
    assert "&lt;script&gt;" in msg
    assert "<script>" not in msg
    assert "evil.example.com" not in msg
    assert '<a href="https://investor.nvidia.com/events">' in msg


def test_catalyst_workflow_sends_only_existing_official_public_documents():
    workflow = Path(".github/workflows/catalyst-watchlist.yml").read_text()
    assert "python -m scripts.send_keyless_official_context" in workflow
    assert "--macro state/runtime/public/data/public_macro.json" in workflow
    assert "--ir-news state/runtime/public/data/ir_news.json" in workflow
    assert "git add state/catalyst/keyless_official_brief_state.json" in workflow
    assert "TELEGRAM_READY == 'true'" in workflow
