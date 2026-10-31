"""Deterministic OHLCV-only liquidity intelligence and source-rights guards."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from options_radar.structure_liquidity_shadow import analyze
from scripts import run_focus_options_private as owner

NY = ZoneInfo("America/New_York")


def candles(*, count=78, extra_both_sides=False, gap=False, open_at="09:30"):
    hour, minute = (int(x) for x in open_at.split(":"))
    begin = datetime(2026, 10, 30, hour, minute, tzinfo=NY)
    rows = []
    for i in range(count):
        tm = begin + timedelta(minutes=i * 5)
        close = 100 + i * .005
        open_ = close
        high = close + .2
        low = close - .2
        if i == 8:
            high = 105.0
        if i == 12:
            low = 95.0
        if i == 22:
            high, close, open_, low = 106.0, 100.0, 100.0, 99.8
            if extra_both_sides:
                low = 94.0
        if i == 23:
            high, close, open_, low = 100.2, 94.0, 100.0, 93.8
        rows.append({
            "timestamp": tm.astimezone(timezone.utc).isoformat(),
            "open": open_, "high": high, "low": low,
            "close": close, "volume": 1000})
    if gap:
        rows.pop(20)
    return rows


def after(rows):
    return (datetime.fromisoformat(rows[-1]["timestamp"])
            + timedelta(minutes=5))


def test_sweep_only_after_known_confirmed_pivot_and_opposing_structure():
    rows = candles(count=45)
    report = analyze(rows, now=after(rows))
    assert report["status"] == "RESEARCH_ONLY"
    kinds = [x["kind"] for x in report["signal_events"]]
    assert "HIGH_SWEEP_PRICE_PROXY" in kinds
    assert "HIGH_SWEEP_THEN_DOWN_STRUCTURAL_BREAK" in kinds
    sweep = next(x for x in report["signal_events"]
                 if x["kind"] == "HIGH_SWEEP_PRICE_PROXY")
    reversal = next(x for x in report["signal_events"]
                    if x["kind"] == "HIGH_SWEEP_THEN_DOWN_STRUCTURAL_BREAK")
    assert sweep["known_at_index"] == 22
    assert sweep["pivot_known_at_index"] == 10
    assert reversal["known_at_index"] == 23
    assert reversal["pivot_known_at_index"] == 14
    assert reversal["execution_authority"] is False
    assert report["actual_order_flow_verified"] is False
    assert report["liquidation_or_stops_observed"] is False
    assert report["win_probability"] is None


def test_prefix_replay_does_not_backdate_sweep_or_reversal():
    rows = candles(count=50)
    full = analyze(rows, now=after(rows))
    for size in (26, 31, 37, 42, 49):
        subset = rows[:size]
        partial = analyze(subset, now=after(subset))
        expected = [x for x in full["signal_events"]
                    if x["known_at_index"] < size]
        assert partial["signal_events"] == expected
    early = analyze(rows[:22], now=after(rows[:22]))
    assert early["status"] == "INSUFFICIENT_COMPLETED_BARS"
    before = analyze(rows[:26], now=after(rows[:26]))
    assert all(x["kind"] != "HIGH_SWEEP_PRICE_PROXY" or
               x["known_at_index"] == 22 for x in before["signal_events"])


def test_incomplete_five_minute_gaps_fail_closed():
    rows = candles(gap=True)
    r = analyze(rows, now=after(rows))
    assert r["status"] == "INCOMPLETE_INTRADAY_BAR_SEQUENCE"
    assert not r["signal_events"]
    assert r["execution_authority"] is False


def test_ambiguous_both_sides_wicks_does_not_identify_order_of_events():
    rows = candles(count=45, extra_both_sides=True)
    r = analyze(rows, now=after(rows))
    events = [x for x in r["signal_events"] if x["known_at_index"] == 22]
    assert any(x["kind"] == "AMBIGUOUS_BOTH_SIDES_WICKED" for x in events)
    assert not any(x["kind"] == "HIGH_SWEEP_PRICE_PROXY" for x in events)
    assert not any(x["kind"] == "LOW_SWEEP_PRICE_PROXY" for x in events)


def test_15m_trend_uses_only_groups_of_three_complete_5m_bars():
    rows = candles()
    r = analyze(rows, now=after(rows))
    assert r["status"] == "RESEARCH_ONLY"
    assert r["trend_15m"] in ("UP", "DOWN", "MIXED")
    assert r["research_confluence_count"] <= 2
    assert r["signal"] == "WAIT"  # historical sweep must not remain current


def test_incomplete_five_minute_candle_cannot_emit_new_event():
    rows = candles(count=45)
    prior = analyze(rows, now=after(rows))
    future = {
        "timestamp": (after(rows) + timedelta(minutes=1)).isoformat(),
        "open": 100.0, "high": 200.0, "low": 90.0,
        "close": 99.0, "volume": 9999999,
    }
    result = analyze(rows + [future], now=after(rows))
    assert prior["signal_events"] == result["signal_events"]
    assert result["execution_authority"] is False


def test_private_report_labels_liquidity_as_research_only():
    msg = owner.owner_report({
        "status": "PRIVATE_RESEARCH_SCAN", "completed": 1,
        "research_watches": 0,
        "by_symbol": {"SPY": {"technical_decision": "WAIT",
            "structure_signal": "HIGH_SWEEP_THEN_DOWN_STRUCTURAL_BREAK",
            "trend_5m": "DOWN", "trend_15m": "DOWN"}}})
    assert "سحب علوي ثم كسر هيكل هابط" in msg
    assert "5م/15م" in msg
    assert "بحثي" in msg
    assert "لا توجد توصيات تنفيذ" in msg
    assert "لا توجد توصيات تنفيذ أو أسعار OPRA" in msg
