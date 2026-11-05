from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from options_radar import signal_ledger as sl

T0 = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)  # 10:00 New York (EST)
OCC = "AMD261106C00250000"
APPROVED = {"approved": True, "state": "CONFIRMED", "blockers": []}
REJECTED = {"approved": False, "state": "NO_TRADE", "blockers": ["v11_execution_quote_not_ready"]}


def _quote(at, bid, ask, source="intrinio-opra", **extra):
    return {"bid": bid, "ask": ask, "quote_timestamp": at.isoformat(), "source": source, **extra}


def _candidate(at=T0, bid=4.9, ask=5.0, source="intrinio-opra", v11=APPROVED, **extra):
    row = {"contract_symbol": OCC, "side": "CALL", "strike": 250, "expiration": "2026-11-06",
           "underlying_price": 248.2, "v11_decision": v11, "telegram_eligible": v11["approved"],
           "reasons": ["اختراق مقاومة اليوم بحجم مرتفع", "VWAP صاعد", "سيولة العقد كافية"],
           "invalidation": {"underlying_level": 244.0, "text_ar": "إغلاق 5 دقائق تحت 244"}}
    row.update(_quote(at, bid, ask, source))
    row.update(extra)
    return row


def _published(**kw):
    built = sl.build_signal(_candidate(**kw), now=T0)
    assert built["accepted"], built["rejections"]
    signal = built["signal"]
    sl.mark_published(signal, at=T0 + timedelta(seconds=5), message_id=77)
    return signal


def test_parse_occ_and_rejects_malformed():
    parsed = sl.parse_occ(OCC)
    assert parsed == {"occ": OCC, "root": "AMD", "expiration": "2026-11-06", "side": "CALL", "strike": 250.0}
    assert sl.parse_occ("AMD261306C00250000") is None  # month 13
    assert sl.parse_occ("AMD 250 CALL") is None
    assert sl.parse_occ("AMD261106C00000000") is None


def test_settlement_profiles_keep_spx_and_spxw_apart():
    spx = sl.settlement_profile("SPX", "2026-11-20")
    spxw = sl.settlement_profile("SPXW", "2026-11-20")
    assert spx["settlement"] == "AM" and spx["last_trade_at"].startswith("2026-11-19T21:00")
    assert spxw["settlement"] == "PM" and spxw["last_trade_at"].startswith("2026-11-20T21:00")
    assert sl.settlement_profile("SPY", "2026-11-20")["settlement_kind"] == "PHYSICAL"


def test_signal_id_is_stable_per_contract_and_session():
    assert sl.signal_id_for(OCC, "2026-11-04") == sl.signal_id_for(OCC, "2026-11-04")
    assert sl.signal_id_for(OCC, "2026-11-04") != sl.signal_id_for(OCC, "2026-11-05")
    assert sl.signal_url("abc").endswith("/options/signal/abc")


@pytest.mark.parametrize("quote,expected", [
    (_quote(T0 - timedelta(seconds=10), 1.0, 1.1), sl.LIVE),
    (_quote(T0 - timedelta(seconds=10), 1.0, 1.1, source="yahoo"), sl.DELAYED),
    ({"bid": 1.0, "ask": 1.1, "source": "intrinio-opra"}, sl.UNAVAILABLE),
    (_quote(T0 - timedelta(seconds=10), 0, 1.1), sl.UNAVAILABLE),
    (_quote(T0 - timedelta(hours=2), 1.0, 1.1), sl.STALE),
    (_quote(T0 + timedelta(minutes=5), 1.0, 1.1), sl.UNAVAILABLE),
])
def test_grade_quote(quote, expected):
    assert sl.grade_quote(quote, now=T0)["grade"] == expected


def test_last_trade_alone_is_never_a_quote():
    grade = sl.grade_quote({"last": 1.2, "last_trade_time": T0.isoformat(), "source": "intrinio-opra"}, now=T0)
    assert grade["grade"] == sl.UNAVAILABLE


def test_confirmed_requires_v11_approval_and_live_quote():
    signal = sl.build_signal(_candidate(), now=T0)["signal"]
    assert signal["decision"] == sl.CONFIRMED and signal["telegram_eligible"]
    assert signal["levels"]["entry_price_basis"] == "ask" and signal["levels"]["exit_price_basis"] == "bid"
    assert signal["levels"]["stop"] == 3.0 and signal["levels"]["targets"] == [7.0, 9.0, 11.0]
    assert signal["contract"]["settlement"] == "PM"

    watch = sl.build_signal(_candidate(source="yahoo", v11=REJECTED), now=T0)["signal"]
    assert watch["decision"] == sl.WATCH and not watch["telegram_eligible"]

    live_unapproved = sl.build_signal(_candidate(v11=REJECTED), now=T0)["signal"]
    assert live_unapproved["decision"] == sl.WATCH and not live_unapproved["telegram_eligible"]


@pytest.mark.parametrize("override,reason", [
    ({"contract_symbol": "BAD"}, "invalid_occ_identity"),
    ({"side": "PUT"}, "side_conflicts_with_occ"),
    ({"strike": 255}, "strike_conflicts_with_occ"),
    ({"adjusted": True}, "adjusted_or_non_standard_contract"),
    ({"v11_decision": None}, "v11_decision_missing"),
])
def test_hard_rejections(override, reason):
    row = _candidate()
    row.update(override)
    if override.get("v11_decision", 1) is None:
        row.pop("v11_decision")
    result = sl.build_signal(row, now=T0)
    assert not result["accepted"] and reason in result["rejections"]


def test_wide_spread_and_expired_contract_are_rejected():
    wide = sl.build_signal(_candidate(bid=3.0, ask=5.0), now=T0)
    assert not wide["accepted"] and "spread_too_wide" in wide["rejections"]
    late = sl.build_signal(_candidate(), now=datetime(2026, 11, 6, 21, 1, tzinfo=timezone.utc))
    assert not late["accepted"] and "contract_no_longer_trading" in late["rejections"]


def test_nothing_is_monitored_before_publication():
    signal = sl.build_signal(_candidate(), now=T0)["signal"]
    assert sl.observe(signal, _quote(T0 + timedelta(minutes=1), 7.5, 7.6), now=T0 + timedelta(minutes=1)) == []
    assert signal["state"] == sl.CREATED


def test_paper_entry_on_ask_then_t1_then_stop_counts_targets_independently():
    s = _published()
    t = T0 + timedelta(minutes=1)
    sl.observe(s, _quote(t, 4.95, 5.05), now=t)
    assert s["state"] == sl.PAPER_ACTIVE and s["paper"]["fill"] == pytest.approx(5.1005)
    t += timedelta(minutes=1)
    sl.observe(s, _quote(t, 7.1, 7.2), now=t)
    assert s["state"] == sl.TARGET_1 and "TARGET_1" in s["targets_hit"]
    t += timedelta(minutes=1)
    sl.observe(s, _quote(t, 2.9, 3.0), now=t)
    assert s["state"] == sl.STOPPED and s["outcome"] == "STOPPED_AFTER_TARGET_1"
    assert s["paper"]["exit"] == 2.9 and s["paper"]["return_pct_after_costs"] < 0


def test_entry_needs_execution_grade_quote():
    s = _published()
    t = T0 + timedelta(minutes=1)
    sl.observe(s, _quote(t, 4.95, 5.05, source="yahoo"), now=t)
    assert s["state"] == sl.ENTRY_ELIGIBLE and s["paper"] is None


def test_same_bar_target_and_stop_is_ambiguous_not_a_win():
    s = _published()
    t = T0 + timedelta(minutes=1)
    sl.observe(s, _quote(t, 4.95, 5.05), now=t)
    t += timedelta(minutes=5)
    sl.observe(s, _quote(t, 5.0, 5.1, bid_low=2.5, bid_high=7.5), now=t)
    assert s["state"] == sl.AMBIGUOUS and s["outcome"] == "AMBIGUOUS" and s["targets_hit"] == {}


def test_replay_and_pre_publication_quotes_are_ignored():
    s = _published()
    t = T0 + timedelta(minutes=1)
    q = _quote(t, 4.95, 5.05)
    sl.observe(s, q, now=t)
    events = len(s["events"])
    assert sl.observe(s, q, now=t + timedelta(seconds=30)) == []
    assert len(s["events"]) == events
    old = _quote(T0 - timedelta(minutes=1), 7.5, 7.6)
    assert sl.observe(s, old, now=t + timedelta(seconds=40)) == []
    assert "TARGET_1" not in s["targets_hit"]


def test_missing_data_is_stale_not_stop_and_resumes():
    s = _published()
    t = T0 + timedelta(minutes=1)
    sl.observe(s, _quote(t, 4.95, 5.05), now=t)
    t2 = t + timedelta(minutes=20)
    sl.sweep(s, now=t2)
    assert s["state"] == sl.DATA_STALE and s["resume_state"] == sl.PAPER_ACTIVE
    sl.observe(s, _quote(t2, 2.0, 2.1, source="yahoo"), now=t2)  # delayed bid below stop
    assert s["state"] == sl.DATA_STALE
    t3 = t2 + timedelta(minutes=1)
    sl.observe(s, _quote(t3, 5.5, 5.6), now=t3)
    assert s["state"] == sl.PAPER_ACTIVE


def test_entry_window_expiry_marks_not_entered():
    s = _published()
    t = T0 + timedelta(minutes=61)
    sl.sweep(s, now=t)
    assert s["state"] == sl.EXPIRED and s["outcome"] == "NOT_ENTERED"


def test_chasing_above_max_entry_never_fills():
    s = _published()
    t = T0 + timedelta(minutes=1)
    sl.observe(s, _quote(t, 5.9, 6.0), now=t)  # max valid entry 5.5
    assert s["state"] == sl.WATCHING and s["paper"] is None


def test_invalidation_before_entry():
    s = _published()
    t = T0 + timedelta(minutes=1)
    sl.observe(s, _quote(t, 5.9, 6.0, underlying_price=243.0), now=t)
    assert s["state"] == sl.INVALIDATED


def test_contract_expiry_leaves_open_paper_unresolved():
    s = _published()
    t = T0 + timedelta(minutes=1)
    sl.observe(s, _quote(t, 4.95, 5.05), now=t)
    sl.sweep(s, now=datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc))
    assert s["state"] == sl.EXPIRED and s["outcome"] == "EXPIRED_OPEN_UNRESOLVED"


def test_ledger_upsert_is_idempotent_and_summary_withholds_win_rate():
    ledger = sl.empty_ledger()
    s = _published()
    assert sl.upsert(ledger, s) is True
    assert sl.upsert(ledger, dict(s)) is False
    summary = sl.summarize(ledger)
    assert summary["total"] == 1 and summary["win_rate_pct"] is None


def test_public_view_withholds_prices_without_display_right():
    s = _published()
    t = T0 + timedelta(minutes=1)
    sl.observe(s, _quote(t, 4.95, 5.05), now=t)
    blocked = sl.public_view(s, display_permitted=False)
    assert blocked["levels"] == {"status": "LICENSE_BLOCKED"}
    assert blocked["quote_at_signal"] == {"status": "LICENSE_BLOCKED"}
    assert all("quote" not in e for e in blocked["events"])
    assert "message_id" not in blocked["telegram"]
    shown = sl.public_view(s, display_permitted=True)
    assert shown["levels"]["stop"] == 3.0


def _family_of(value, families):
    return "yahoo" if "yahoo" in str(value).lower() and "yahoo" in families else None


@pytest.mark.parametrize("source,allow,expected", [
    ("intrinio-opra", (), False),               # unknown right: blocked
    ("intrinio-opra", ("intrinio",), True),     # owner recorded the display right
    ("yahoo", ("yahoo",), False),               # a closed family can never be allowlisted
    ("", ("intrinio",), False),
])
def test_public_display_is_allowlist_only(source, allow, expected):
    assert sl.display_permitted(source, closed_families=["yahoo"], family_of=_family_of,
                                display_sources=allow) is expected


def test_public_ledger_blocks_prices_by_default():
    ledger = sl.empty_ledger()
    sl.upsert(ledger, _published())
    public = sl.build_public_ledger(ledger, now=T0, closed_families=[], family_of=_family_of)
    assert public["signals"][0]["quote_series"] == {"status": "LICENSE_BLOCKED"}
    assert public["research_only"] is True and public["summary"]["total"] == 1


def test_telegram_text_is_escaped_bounded_and_links_the_page():
    s = _published()
    s["reasons"] = ["<script>x</script>"]
    text = sl.telegram_text(s)
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert s["url"] in text and len(text) < 4096
    assert "GHAZI RADAR Ω | توصية خيارات" in text
