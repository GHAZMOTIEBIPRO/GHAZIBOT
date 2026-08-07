from options_radar.omega_catalyst_intelligence import (
    build_catalyst_intelligence,
    classify_catalyst_event,
)


def event(form, headline, evidence="", score=0, source="SEC EDGAR", symbol="TEST"):
    return {
        "symbol": symbol,
        "company": "Test Corp",
        "event_date": "2026-08-07",
        "form": form,
        "headline": headline,
        "evidence": evidence,
        "score": score,
        "source": source,
        "url": "https://example.test/event",
    }


def test_required_catalyst_fixtures_classify_with_structured_output():
    cases = [
        (event("8-K", "FDA approval", "approved by the FDA", 25), "FDA_APPROVAL", "bullish"),
        (event("8-K", "Complete Response Letter", "CRL received", -25), "FDA_CRL", "bearish"),
        (event("8-K", "Definitive merger agreement", "", 24), "MERGER_DEFINITIVE", "bullish"),
        (event("8-K", "Termination of the merger agreement", "", -22), "MERGER_TERMINATED", "bearish"),
        (event("SC 13D", "Schedule 13D", "", 14), "STRATEGIC_OWNERSHIP_13D", "mixed"),
        (event("4", "Form 4", "<transactionCode>P</transactionCode> open market purchase", 18), "INSIDER_OPEN_MARKET_PURCHASE", "bullish"),
        (event("4", "Form 4 option exercise", "exercise of option; grant", 0), "INSIDER_DERIVATIVE_OR_GRANT", "neutral"),
        (event("8-K", "ATM financing", "at-the-market offering", -22), "ATM", "bearish"),
        (event("424B5", "424B5 public offering", "public offering", -23), "PUBLIC_OFFERING", "bearish"),
        (event("8-K", "Positive topline", "met its primary endpoint", 21), "TRIAL_POSITIVE", "bullish"),
        (event("8-K", "Trial failed", "did not meet the primary endpoint", -24), "TRIAL_FAILED", "bearish"),
    ]
    for raw, expected_category, expected_bias in cases:
        row = classify_catalyst_event(raw)
        assert row["category"] == expected_category
        assert row["directional_bias"] == expected_bias
        assert 0 <= row["materiality"] <= 100
        assert 0 <= row["confidence"] <= 1
        assert 0 <= row["dilution_risk"] <= 100
        assert row["source"]


def test_form4_grant_is_not_promoted_to_open_market_purchase():
    row = classify_catalyst_event(
        event("4", "Equity award", "option exercise grant restricted stock", 18)
    )
    assert row["category"] == "INSIDER_DERIVATIVE_OR_GRANT"
    assert row["directional_bias"] == "neutral"


def test_same_event_from_sec_and_yahoo_is_clustered_not_double_scored():
    sec = event("8-K", "Definitive merger agreement", "", 24, "SEC EDGAR", "MRG")
    yahoo = event("NEWS", "Company enters merger agreement", "", 18, "Yahoo Finance News", "MRG")
    intel = build_catalyst_intelligence([sec, yahoo], [])
    assert intel["events_received"] == 2
    assert intel["event_clusters"] == 1
    assert intel["duplicates_collapsed"] == 1
    cluster = intel["clusters"][0]
    assert cluster["confirmation_count"] == 2
    assert cluster["primary_source"] == "SEC EDGAR"
    assert cluster["causal_firewall"]["probability_of_profit"] is None


def test_dilution_overhang_is_explicit_risk():
    row = classify_catalyst_event(
        event("424B5", "Prospectus supplement", "registered direct offering", -25)
    )
    assert row["dilution_risk"] >= 80
    assert row["directional_bias"] == "bearish"
