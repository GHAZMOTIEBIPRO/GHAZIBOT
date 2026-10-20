from datetime import datetime, timezone

import pytest

from options_radar.news_impact import annotate, classify

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
FRESH = "2026-10-20T13:00:00+00:00"


def news(headline, **extra):
    return {"headline": headline, "published_at": FRESH, "authority": "NEWS_SEARCH_ATTENTION_ONLY",
            "official_sec_filing": False, "issuer_release_authenticated": False, **extra}


@pytest.mark.parametrize("headline", [
    "Acme Bio receives FDA approval for lead drug",
    "Acme Corp announces $20 million registered direct offering",
    "Acme files for Chapter 11 bankruptcy",
    "Acme enters definitive merger agreement with Beta",
])
def test_high_potency_unofficial_is_capped_at_medium(headline):
    out = classify(news(headline), now=NOW)
    assert out["impact_level"] == "MEDIUM"
    assert out["impact_rules"] == ["R3_ISSUER_EVENT_HIGH", "R1_UNOFFICIAL_SOURCE_CAP"]


def test_high_potency_official_stays_high():
    out = classify(news("Acme Bio receives FDA approval", official_sec_filing=True), now=NOW)
    assert out["impact_level"] == "HIGH"


def test_earnings_medium_generic_low():
    assert classify(news("Acme reports third-quarter results"), now=NOW)["impact_level"] == "MEDIUM"
    assert classify(news("Acme to present at investor conference"), now=NOW)["impact_level"] == "LOW"


@pytest.mark.parametrize("headline", [
    "Nvidia (NVDA) Stock Price Lags Massive Earnings Growth—A Compelling Value Opportunity",
    "Rigetti Computing (RGTI) Could Be 26% Undervalued On EPS Concerns Despite Revenue Growth",
    "What to Expect From Advanced Micro Devices' Q3 2026 Earnings Report",
    "Should you buy Acme before FDA approval?",
])
def test_unofficial_opinion_is_low(headline):
    out = classify(news(headline), now=NOW)
    assert out["impact_level"] == "LOW"
    assert out["impact_rules"] == ["R3_OPINION_OR_ANALYSIS_LOW"]


def test_older_than_72h_drops_one_level():
    out = classify(news("Acme reports earnings", published_at="2026-10-16T13:00:00+00:00"), now=NOW)
    assert out["impact_level"] == "LOW" and "R4_OLDER_THAN_72H" in out["impact_rules"]


def test_macro_rules():
    cpi = {"title": "Consumer Price Index", "authority": "OFFICIAL_SCHEDULE",
           "scheduled_at": "2026-10-24T12:30:00+00:00"}
    eci = {"title": "Employment Cost Index", "authority": "OFFICIAL_SCHEDULE"}
    other = {"title": "Metropolitan Area Employment", "authority": "OFFICIAL_SCHEDULE"}
    assert classify(cpi, now=NOW, macro=True)["impact_level"] == "HIGH"
    assert classify(eci, now=NOW, macro=True)["impact_level"] == "MEDIUM"
    assert classify(other, now=NOW, macro=True)["impact_level"] == "LOW"


def test_annotate_marks_every_list_and_states_policy():
    payload = {"google_news_attention": [news("Acme reports earnings")],
               "bls_upcoming": [{"title": "Employment Situation", "authority": "OFFICIAL_SCHEDULE"}],
               "fed_monetary": [], "press_wire_attention": None}
    out = annotate(payload, now=NOW)
    assert out["google_news_attention"][0]["impact_level"] == "MEDIUM"
    assert out["bls_upcoming"][0]["impact_level"] == "HIGH"
    policy = out["impact_policy"]
    assert policy["impact_is_direction"] is False and policy["impact_is_probability"] is False
    assert policy["unofficial_max_level"] == "MEDIUM"
