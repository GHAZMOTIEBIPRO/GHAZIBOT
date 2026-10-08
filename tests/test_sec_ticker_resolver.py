from options_radar.sec_ticker_resolver import resolve_sec_ticker


def test_exact_official_ticker_resolves_to_cik():
    payload = {"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple Inc."}}
    result = resolve_sec_ticker(payload, "aapl")
    assert result["cik"] == 320193
    assert result["source"] == "SEC_COMPANY_TICKERS"
    assert result["research_only"] is True


def test_ambiguous_or_invalid_mapping_fails_closed():
    payload = {"0": {"ticker": "ABC", "cik_str": 12, "title": "One"},
               "1": {"ticker": "ABC", "cik_str": 34, "title": "Two"}}
    assert resolve_sec_ticker(payload, "ABC") is None
    assert resolve_sec_ticker(payload, "../ABC") is None
    assert resolve_sec_ticker({"0": {"ticker": "ABC", "cik_str": True, "title": "Bad"}}, "ABC") is None
