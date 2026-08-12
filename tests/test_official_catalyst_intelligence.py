from options_radar.official_catalyst_intelligence import build_catalyst_intelligence


def _event(source: str, *, symbol: str = "TEST", headline: str = "Definitive merger agreement", form: str = "8-K"):
    return {
        "symbol": symbol,
        "company": "Test Corp",
        "event_date": "2026-08-13",
        "form": form,
        "headline": headline,
        "evidence": "definitive merger agreement",
        "score": 24,
        "confidence": 0.94,
        "source": source,
        "url": "https://www.sec.gov/Archives/test" if "SEC" in source else "https://example.test/news",
    }


def test_sec_plus_yahoo_is_one_independent_confirmation_family():
    intel = build_catalyst_intelligence(
        [_event("SEC EDGAR Precision Full-Text"), _event("Yahoo Finance News")],
        [],
    )
    cluster = intel["by_symbol"]["TEST"]
    assert cluster["official_confirmed"] is True
    assert cluster["primary_cause_eligible"] is True
    assert cluster["source_family"] == "sec"
    assert cluster["confirmation_count"] == 1
    assert cluster["cause_status_ar"] == "سبب مؤكد رسميًا"


def test_attention_only_source_cannot_establish_primary_cause():
    event = _event("Reddit", headline="FDA approval rumor")
    event["url"] = "https://reddit.com/r/stocks/example"
    intel = build_catalyst_intelligence([event], [])
    cluster = intel["by_symbol"]["TEST"]
    assert cluster["attention_only"] is True
    assert cluster["primary_cause_eligible"] is False
    assert cluster["catalyst_quality"] <= 45
    assert "غير مثبت" in cluster["cause_status_ar"]


def test_two_sec_paths_do_not_double_count_confirmation():
    intel = build_catalyst_intelligence(
        [_event("SEC EDGAR"), _event("SEC EDGAR Precision Full-Text")],
        [],
    )
    cluster = intel["by_symbol"]["TEST"]
    assert cluster["confirmation_count"] == 1
    assert cluster["independent_confirmation_families"] == ["sec"]
