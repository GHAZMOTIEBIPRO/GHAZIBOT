from datetime import datetime, timedelta, timezone

from options_radar.guardian_research import (
    catalyst_report_ar,
    chart_risk_context,
    record_option_quote_snapshot,
)
from options_radar.contract_guardian import update_contract_guardian
from scripts.send_contract_guardian_updates import _fingerprint, _message


NOW = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)


def _quote(*, timestamp=None, bid=2.0, ask=2.1):
    return {
        "symbol": "ABC",
        "contract_symbol": "ABC261120C00050000",
        "side": "CALL",
        "option_type": "call",
        "expiration": "2026-11-20",
        "strike": 50.0,
        "underlying_price": 49.0,
        "bid": bid,
        "ask": ask,
        "iv": 0.40,
        "source": "free_research_vendor",
        "quote_timestamp": timestamp if timestamp is not None else NOW.isoformat(),
    }


def _payload(*, official=True, direction="bullish", timestamp=None):
    quote = _quote(timestamp=timestamp)
    primary = {**quote, "alert_stage": "WATCH", "premium_targets": {}}
    stock = {
        "symbol": "ABC",
        "price": 49.0,
        "target_1": 52.0,
        "target_2": 55.0,
        "invalidation": 46.0,
        "technical_direction": direction,
        "relative_volume": 3.0,
        "breakout_pressure_score": 82.0,
        "rsi": 65.0,
        "setup_status": "qualified",
    }
    return {
        "stocks": [stock],
        "expiry_radar": {
            "tabs": {"all_expirations": {"calls": [quote], "puts": []}}
        },
        "option_contract_intelligence": {"by_symbol": {"ABC": {"primary": primary}}},
        "omega": {
            "opportunities": [],
            "catalyst_intelligence": {
                "by_symbol": {
                    "ABC": {
                        "headline": "Government contract",
                        "primary_source": "SEC EDGAR" if official else "social feed",
                        "primary_url": "https://www.sec.gov/Archives/example" if official else "",
                        "official_confirmed": official,
                        "issuer_primary": False,
                        "category_normalized": "MATERIAL_CONTRACT",
                        "directional_bias": "bullish",
                        "explosion_impact": {
                            "score": 91,
                            "drivers_ar": ["إفصاح رسمي", "حجم تداول مرتفع"],
                            "risks_ar": ["السبريد واسع"],
                        },
                    }
                }
            },
        },
    }


def test_self_collected_history_does_not_forge_timestamps_or_duplicates():
    valid = _quote()
    history, result = record_option_quote_snapshot(
        [], valid, now=NOW, max_age_minutes=120
    )
    assert result["recorded"] is True
    assert len(history) == 1
    assert history[0]["execution_grade"] is False
    assert history[0]["quote_timestamp"] == NOW.isoformat()

    repeated, result = record_option_quote_snapshot(
        history, valid, now=NOW + timedelta(minutes=5), max_age_minutes=120
    )
    assert result["reason"] == "duplicate_provider_snapshot"
    assert len(repeated) == 1

    unstamped = dict(valid)
    unstamped.pop("quote_timestamp")
    unstamped["updated_at"] = NOW.isoformat()
    rejected, result = record_option_quote_snapshot(
        history, unstamped, now=NOW, max_age_minutes=120
    )
    assert result["reason"] == "missing_provider_quote_time"
    assert len(rejected) == 1


def test_stale_future_and_crossed_quotes_are_not_added():
    stale = _quote(timestamp=(NOW - timedelta(hours=4)).isoformat())
    future = _quote(timestamp=(NOW + timedelta(minutes=30)).isoformat())
    crossed = _quote(bid=2.2, ask=2.1)
    for row in (stale, future, crossed):
        history, note = record_option_quote_snapshot(
            [], row, now=NOW, max_age_minutes=120
        )
        assert history == []
        assert note["recorded"] is False


def test_chart_rejects_direction_mismatch_without_overriding_original_side():
    target = {"t1": {"price": 52}, "invalidation": {"price": 46}}
    chart = chart_risk_context(
        {"price": 49, "technical_direction": "bearish", "relative_volume": 2},
        "CALL",
        target,
    )
    assert chart["state"] == "DIRECTION_CONFLICT"
    assert chart["direction_conflict"] is True
    assert chart["research_only"] is True


def test_unverified_news_does_not_receive_official_impact_rating():
    stock = {"price": 49}
    chart = chart_risk_context(stock, "CALL", {})
    report = catalyst_report_ar(
        "ABC",
        {
            "headline": "Rumor",
            "primary_source": "social",
            "official_confirmed": False,
            "explosion_impact": {"score": 99},
        },
        stock,
        chart,
    )
    assert report["verification"] == "UNVERIFIED"
    assert report["impact_score"] is None
    assert "غير مثبت" in report["report_ar"]


def test_guardian_embeds_chart_news_and_free_quote_history_without_v11_promotion():
    payload = _payload()
    report, state = update_contract_guardian(payload, {}, now=NOW)
    tracked = next(iter(state["contracts"].values()))
    assert tracked["quote_history_count"] == 1
    assert tracked["explosion_thesis"]["verification"] == "OFFICIAL"
    assert tracked["explosion_thesis"]["impact_score"] == 91
    assert tracked["chart_health"]["state"] == "ALIGNED_PRESSURE"
    assert tracked["side"] == "CALL"
    assert tracked["quote_snapshots"][0]["execution_grade"] is False
    assert report["can_promote_v11"] is False
    card = _message(tracked)
    assert "قراءة الشارت" in card
    assert "حالة الخبر" in card
    assert "سجل أسعار العقد المجاني" in card
    assert "فتح المصدر الأصلي" in card

    report_2, state = update_contract_guardian(payload, state, now=NOW + timedelta(minutes=1))
    tracked_2 = next(iter(state["contracts"].values()))
    assert tracked_2["quote_history_count"] == 1
    assert tracked_2["mfe_pct"] == tracked["mfe_pct"]
    assert report_2["can_promote_v11"] is False


def test_telegram_fingerprint_catches_new_official_news_or_chart_conflict():
    payload = _payload()
    _, state = update_contract_guardian(payload, {}, now=NOW)
    tracked = next(iter(state["contracts"].values()))
    old_fingerprint = _fingerprint(tracked)
    new_payload = _payload(direction="bearish")
    new_payload["omega"]["catalyst_intelligence"]["by_symbol"]["ABC"]["headline"] = "Approval amended"
    _, state = update_contract_guardian(
        new_payload, state, now=NOW + timedelta(minutes=2)
    )
    updated = next(iter(state["contracts"].values()))
    assert _fingerprint(updated) != old_fingerprint
    assert updated["chart_health"]["direction_conflict"] is True


def test_guardian_stale_quote_does_not_inflate_mfe():
    old = (NOW - timedelta(hours=5)).isoformat()
    report, state = update_contract_guardian(
        _payload(timestamp=old), {}, now=NOW
    )
    tracked = next(iter(state["contracts"].values()))
    assert tracked["data_stale"] is True
    assert tracked["quote_history_count"] == 0
    assert tracked["mfe_pct"] is None
    assert tracked["mae_pct"] is None
    assert report["decision_authority"] is False
