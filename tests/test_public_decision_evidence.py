"""Offline proofs for public candidate first sighting + historical audit honesty."""
from datetime import datetime, timedelta, timezone

import pytest
from scripts.build_public_decision_brief import build_brief, safe_link
from scripts.publish_stock_audit_summary import build_summary

NOW = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)


def fixture() -> dict:
    return {
        "generated_at": (NOW-timedelta(minutes=1)).isoformat(),
        "stocks": [
            {"symbol":"TSLA","rating":"A","score":89,"setup_side":"CALL",
             "setup_status":"WATCH","price":450.12,"relative_volume":2.1,
             "catalyst_url":"https://www.sec.gov/test"},
            {"symbol":"BAD <script>","price":7},
        ],
        "catalysts":[
            {"symbol":"TSLA","headline":"Official 8-K? Verify first","source":"SEC EDGAR",
             "url":"https://www.sec.gov/Archives/example.htm"},
            {"symbol":"BAD?","headline":"fake","url":"javascript:alert(1)"},
        ],
    }


def test_frozen_original_observation_is_not_rewritten():
    first, state = build_brief(fixture(), None, now=NOW)
    assert first["journal"]["true_win_rate"] is None
    assert first["journal"]["net_trading_return"] is None
    assert first["live_trade_quotes_verified"] is False
    assert first["stocks"][0]["is_verified_official_catalyst"] is False
    assert len(first["stocks"]) == 1
    assert first["catalysts"][0]["status"] == "UNVERIFIED_CONTEXT_ONLY"
    key = next(iter(state["records"]))
    assert state["records"][key]["price_at_first_sighting"] == 450.12
    payload = fixture()
    payload["generated_at"] = (NOW-timedelta(seconds=10)).isoformat()
    payload["stocks"][0]["price"] = 470
    newer, saved = build_brief(payload, state, now=NOW)
    assert len(saved["records"]) == 1
    assert saved["records"][key]["price_at_first_sighting"] == 450.12
    assert newer["journal"]["outcomes_graded_here"] == 0


def test_missing_and_future_source_timestamps_fail_closed():
    bad=fixture()
    bad.pop("generated_at")
    with pytest.raises(ValueError):
        build_brief(bad,None,now=NOW)
    bad["generated_at"]=(NOW+timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):
        build_brief(bad,None,now=NOW)
    bad["generated_at"]=(NOW-timedelta(hours=4)).isoformat()
    with pytest.raises(ValueError):
        build_brief(bad,None,now=NOW)


def test_disallow_non_https_links_and_corrupt_journal():
    assert safe_link("javascript:alert(1)") is None
    assert safe_link("http://example.com") is None
    assert safe_link("https://ok.example.com/story") is not None
    with pytest.raises(ValueError,match="schema"):
        build_brief(fixture(),{"schema":"corrupted","records":{}},now=NOW)


def test_audit_does_not_advertise_unverified_win_rate():
    audit={
        "mode":"HISTORICAL_5M_OUTCOME_AUDIT","decision_authority":False,
        "coverage":{"records":40,"eligible_records":40,"covered_60m":36,
                    "ambiguous":9,"non_decisive":4,"pending":2,"unavailable":3,
                    "independent_60m_sessions":11},
        "promotion_gate":{"coverage_ready":True,"minimum_independent_sessions":10,
                          "minimum_60m_coverage_pct":90.0,"live_promotion_allowed":False},
    }
    public=build_summary(audit,now=NOW)
    assert public["coverage"]["ambiguous"] == 9
    assert public["coverage"]["covered_60m"] == 36
    assert public["promotion_gate"]["live_promotion_allowed"] is False
    assert public["proven_edge"] is False
    assert public["verified_win_rate_pct"] is None
    assert public["realized_portfolio_pnl"] is False


def test_audit_rejects_unverified_authority_and_invalid_coverage():
    with pytest.raises(ValueError):
        build_summary({"mode":"HISTORICAL_5M_OUTCOME_AUDIT"},now=NOW)
    with pytest.raises(ValueError):
        build_summary({"mode":"HISTORICAL_5M_OUTCOME_AUDIT",
                       "decision_authority":False,
                       "coverage":{"records":2,"covered_60m":5}},now=NOW)


def test_primary_sec_event_prioritized_but_never_called_guaranteed_bullish():
    from scripts.build_public_decision_brief import catalyst_focus, primary_event
    payload = fixture()
    payload["stocks"][0]["relative_volume"] = 2.4
    payload["catalysts"] = [
        {"symbol": "TSLA", "source": "ClinicalTrials.gov",
         "headline": "Unrelated sponsor generic registry update",
         "form": "REGISTRY_UPDATE",
         "event_date": "2026-10-18",
         "url": "https://clinicaltrials.gov/study/NCT12345678",
         "score": 100},
        {"symbol": "TSLA", "source": "SEC EDGAR",
         "headline": "8-K material event; investigate actual impact",
         "form": "8-K",
         "event_date": "2026-10-17",
         "url": "https://www.sec.gov/Archives/example.htm",
         "score": 12},
    ]
    assert primary_event(payload["catalysts"][0]) is False
    assert primary_event(payload["catalysts"][1]) is True
    report,_ = build_brief(payload,None,now=NOW)
    focus = report["catalyst_focus"]
    assert focus["schema"] == "ghazi.catalyst_focus.v1"
    assert len(focus["issuer_primary_events"]) == 1
    assert focus["event_counts"]["clinical_registry_excluded_from_upside_confirmation"] == 1
    candidate = focus["upside_watch"][0]
    assert candidate["symbol"] == "TSLA"
    assert candidate["has_primary_publication"] is True
    assert candidate["research_label"] == "PRIMARY_EVENT_PLUS_RELATIVE_VOLUME_WATCH"
    assert candidate["price_rise_guaranteed"] is False
    assert candidate["is_recommendation"] is False
    assert focus["issuer_primary_events"][0]["direction_confirmed"] is False
    assert report["catalysts"][0]["source"] == "SEC EDGAR"


def test_clinical_registry_and_unsupported_domains_never_confirm_issuer_news():
    from scripts.build_public_decision_brief import catalyst_focus,primary_event
    raw = [
        {"source":"SEC EDGAR","url":"https://sec.gov.evil.invalid/fake","symbol":"MRNA"},
        {"source":"SEC EDGAR","url":"https://news.invalid/filing","symbol":"MRNA"},
        {"source":"ClinicalTrials.gov","url":"https://clinicaltrials.gov/study/NCT98765432","symbol":"MRNA"},
        {"source":"Unknown","url":"https://www.sec.gov/Archives/test","symbol":"MRNA"},
    ]
    assert all(primary_event(x) is False for x in raw)
    result = catalyst_focus({"catalysts":raw}, [
        {"symbol":"MRNA","direction_research":"UP","rvol":3.0,
         "score":87,"rating":"A","stage":"WATCH","observed_price":19.0}
    ],as_of=NOW)
    assert result["issuer_primary_events"] == []
    assert result["upside_watch"][0]["has_primary_publication"] is False
    assert result["upside_watch"][0]["research_label"] == "PRICE_MOMENTUM_WITHOUT_VERIFIED_NEWS"


def test_put_stocks_are_not_promoted_to_upside_on_news():
    from scripts.build_public_decision_brief import catalyst_focus
    focus=catalyst_focus({"catalysts":[
        {"symbol":"SOFI","source":"SEC EDGAR","event_date":"2026-10-17",
         "url":"https://sec.gov/example","headline":"8-K"},
    ]},[{"symbol":"SOFI","direction_research":"PUT","rvol":6.2,
          "observed_price":14.0,"score":99,"rating":"A","stage":"WATCH"}],as_of=NOW)
    assert focus["issuer_primary_events"]
    assert focus["upside_watch"] == []
