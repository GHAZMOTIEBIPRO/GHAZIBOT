"""Score only measured source-readiness. Never conflate 100 with profitable trades."""
from datetime import datetime, timedelta, timezone

from scripts.build_site_strength import WEIGHTS, score

NOW = datetime(2026, 10, 19, 11, tzinfo=timezone.utc)


def charts(now=NOW, count=20):
    return {
        "schema": "ghazi.stock_charts.v1",
        "generated_at": now.isoformat(),
        "provider_source_family": "yahoo",
        "quote_execution_eligible": False,
        "coverage": {
            "requested": 20,
            "with_daily": count,
            "with_1h": count,
            "with_15m": count,
            "with_5m": count,
        },
    }


def agreement(now=NOW):
    return {
        "schema": "ghazi.source_consensus_status.v1",
        "generated_at": now.isoformat(),
        "source_price_families": ["yahoo"],
        "independent_price_comparison": "NOT_VERIFIED",
        "independent_confirmations": 0,
        "quote_execution_eligible": False,
        "massive_market_data_published": False,
    }


def sec(now=NOW):
    return {
        "schema": "ghazi.sec_issuer_pulse.v1",
        "generated_at": now.isoformat(),
        "status": "UNAVAILABLE",
        "coverage": {"issuers_inspected": 0, "filings_verified": 0},
        "filings": [],
        "policy": {"positive_news_inferred": False},
    }


def options(now=NOW):
    return {
        "schema": "ghazi.free_options_source_pulse.v1",
        "generated_at": now.isoformat(),
        "research_only": True,
        "trading_authority": False,
        "option_execution_eligible": False,
        "filingpulse": {"status": "NO_API_KEY_HEALTH_ONLY", "health_reachable": True,
                        "events": []},
        "occ_open_interest": {"status": "UNKNOWN_LAYOUT", "not_live_quote": True,
                              "not_trade_flow": True, "open_interest": None},
    }


def walk():
    return {
        "mode": "EXPANDING_SESSION_WALK_FORWARD",
        "decision_authority": False,
        "live_promotion_allowed": False,
        "data_policy": {
            "random_split_allowed": False,
            "future_session_training_allowed": False,
        },
        "status": "NOT_READY",
        "gate": {"coverage_60m_pct": 64.15,
                 "independent_60m_sessions": 26, "ready": False},
        "metrics": {"oos_sessions": 0, "oos_records": 0},
        "research_passed": False,
    }


def run(**overrides):
    feeds = {"charts": charts(), "agreement": agreement(), "sec": sec(),
             "free_options": options(), "walk_forward": walk()}
    feeds.update(overrides)
    return score(**feeds, now=NOW)


def group(report):
    return {row["id"]: row["earned"] for row in report["components"]}


def test_known_outage_state_scores_research_only_not_90_pct_claim():
    result = run()
    points = group(result)
    assert sum(WEIGHTS.values()) == 100
    assert result["strength_score"] == 41
    assert points == {
        "charts": 25.0,
        "independent_prices": 0.0,
        "issuer_filings": 0.0,
        "options_market_data": 0.0,
        "walk_forward": 6.28,
        "feed_operations": 10,
    }
    assert result["score_is_prediction_win_rate"] is False
    assert result["score_includes_visual_ui_audit"] is False
    assert result["research_only"] is True
    assert result["execution_authority"] is False


def test_old_reports_lose_points_and_cannot_claim_upgraded_prices():
    stale = NOW - timedelta(days=9)
    result = run(charts=charts(stale), agreement=agreement(stale),
                 sec=sec(stale), free_options=options(stale))
    assert group(result)["charts"] == 0
    assert group(result)["feed_operations"] == 0
    assert group(result)["independent_prices"] == 0
    assert result["strength_score"] <= 7


def test_unlicensed_false_independence_cannot_raise_score():
    original = run()
    fake = {**agreement(), "independent_confirmations": 4,
            "independent_price_comparison": "VERIFIED_LICENSED",
            "licensed_independent_non_display_analysis": False}
    assert group(run(agreement=fake))["independent_prices"] == 0
    assert run(agreement=fake)["strength_score"] == original["strength_score"]


def test_partial_timeframes_award_proportion_not_fabricate_bars():
    got = run(charts=charts(count=10))
    assert group(got)["charts"] == 12.5
    out = run(charts={**charts(), "coverage": {
        "requested": 20, "with_daily": 21,
        "with_1h": 20, "with_15m": 20, "with_5m": 20,
    }})
    assert group(out)["charts"] == 0


def test_third_party_filing_is_not_counted_as_direct_sec():
    f = options()
    f["filingpulse"] = {
        "status": "THIRD_PARTY_RESEARCH_ONLY",
        "events": [{"third_party_source": "FILINGPULSE_SEC_DERIVED",
                    "official_sec_api_response_verified": False,
                    "positive_catalyst_verified": False}],
    }
    assert group(run(free_options=f))["issuer_filings"] == 5
    f["filingpulse"]["events"][0]["official_sec_api_response_verified"] = True
    assert group(run(free_options=f))["issuer_filings"] == 0


def test_occ_historical_never_grants_opra_execution_points():
    f = options()
    f["occ_open_interest"] = {
        "status": "HISTORICAL_DAILY_AGGREGATE",
        "not_live_quote": True, "not_trade_flow": True,
        "report_date": "2026-10-16",
        "open_interest": {"AAPL": 2000, "TSLA": 600},
    }
    assert group(run(free_options=f))["options_market_data"] == 5
    f["occ_open_interest"]["report_date"] = "2026-09-01"
    assert group(run(free_options=f))["options_market_data"] == 0


def test_verified_oos_requires_real_samples_not_implied_profit():
    w = walk()
    w.update({"status": "SHADOW_RESEARCH", "research_passed": True})
    w["gate"] = {"coverage_60m_pct": 91, "independent_60m_sessions": 11,
                 "ready": True}
    w["metrics"] = {"oos_sessions": 4, "oos_records": 42}
    verified = run(walk_forward=w)
    assert group(verified)["walk_forward"] == 15
    assert verified["score_is_prediction_win_rate"] is False
    w["metrics"]["oos_records"] = 0
    assert group(run(walk_forward=w))["walk_forward"] == 8


def test_missing_or_corrupt_policy_stays_zero_and_never_divides_by_zero():
    assert group(run(charts={**charts(), "coverage": {"requested": 0}}))[
        "charts"] == 0
    x = walk()
    x["data_policy"]["random_split_allowed"] = True
    assert group(run(walk_forward=x))["walk_forward"] == 0


def test_clock_anomaly_and_negative_values_cannot_increase_readiness():
    future = NOW + timedelta(days=7)
    assert group(run(sec=sec(future)))["feed_operations"] == 8
    abnormal = charts()
    abnormal["coverage"]["with_daily"] = -3
    assert group(run(charts=abnormal))["charts"] == 0
