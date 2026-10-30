"""Alpaca pagination, option-bar provenance and owner-only market-data tests."""
from datetime import datetime, timedelta, timezone

from options_radar.core_options_strategy import rank_contracts
from scripts import run_focus_options_private as private

NOW = datetime(2026, 10, 30, 19, 20, tzinfo=timezone.utc)
CODE = "SPY261102C00755000"


class Reply:
    status_code = 200
    def __init__(self, payload):
        self.payload = payload
        self.content = b'{"safe":"fixture"}'
    def json(self):
        return self.payload


class Pages:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
    def get(self, url, params, headers, timeout):
        self.calls.append({"path": url.split(".markets")[-1], "params": params})
        return Reply(self.pages.get(params.get("page_token", ""), {}))


def test_collect_pages_merges_complete_contract_collection():
    session = Pages({
        "": {"snapshots": {"A": {"greeks": {}}}, "next_page_token": "two"},
        "two": {"snapshots": {"B": {"greeks": {}}}},
    })
    result = private._collect_pages(
        session, private.MARKET, "/v1beta1/options/snapshots/SPY",
        query={"limit": 1000}, key="fixture", secret="fixture",
        field="snapshots")
    assert result["complete"] is True
    assert result["pages"] == 2
    assert list(result["snapshots"]) == ["A", "B"]
    assert session.calls[1]["params"]["page_token"] == "two"


def test_collect_pages_denies_incomplete_or_repeated_cursors():
    session = Pages({
        "": {"option_contracts": [{"symbol": "A"}], "next_page_token": "p"},
        "p": {"option_contracts": [{"symbol": "B"}], "next_page_token": "p"},
    })
    assert private._collect_pages(
        session, private.TRADING, "/v2/options/contracts",
        query={}, key="fixture", secret="fixture",
        field="option_contracts") == {}
    session = Pages({
        "": {"snapshots": {"A": {}}, "next_page_token": "p"},
        "p": {"snapshots": {"B": {}}, "next_page_token": "q"},
        "q": {"snapshots": {"C": {}}, "next_page_token": "r"},
    })
    assert private._collect_pages(
        session, private.MARKET, "/v1beta1/options/snapshots/SPY",
        query={}, key="fixture", secret="fixture", field="snapshots") == {}


def test_completed_option_ohlcv_is_real_delayed_and_volume_partial():
    start = datetime(2026, 10, 30, 18, 35, tzinfo=timezone.utc)
    data = [{"t": (start + timedelta(minutes=5*i)).isoformat(),
             "o": 1.6 + .03*i, "h": 1.67 + .03*i,
             "l": 1.57 + .03*i, "c": 1.63 + .03*i, "v": 120+i}
            for i in range(5)]
    # The latest bar at 18:55 cannot pass the extra 15+5m historical cut
    # against the NOW=19:20 fixture? It can; 18:55+5 <=19:05.
    session = Pages({"": {"bars": {CODE: data}}})
    result = private._completed_option_history(
        session, CODE, now=NOW, key="fixture", secret="fixture")
    assert result["status"] == "VERIFIED_DELAYED_OPTION_OHLCV"
    assert result["bar_count"] == 5
    assert result["latest_session_observed_volume_partial"] == sum(120+i for i in range(5))
    assert result["latest_session_coverage_partial"] is True
    assert result["execution_eligible"] is False
    assert session.calls[0]["params"]["timeframe"] == "5Min"
    assert "feed" not in session.calls[0]["params"]  # Actual historical OPRA bars.


def test_historical_option_bar_endpoint_rejects_incomplete_page():
    session = Pages({"": {"bars": {CODE: []}, "next_page_token": "next"}})
    result = private._completed_option_history(
        session, CODE, now=NOW, key="fixture", secret="fixture")
    assert result["bar_count"] == 0
    assert result["status"] == "NO_VERIFIED_DELAYED_OPTION_BARS"


def test_contract_selection_rejects_old_oi_even_with_good_quote():
    candidate = {"symbol": CODE, "type": "call", "expiration": "2026-11-02",
                 "strike": 755, "delta": .5, "gamma": .03,
                 "open_interest": 1500, "open_interest_date": "2026-10-20",
                 "volume": None,
                 "latest_quote": {
                     "timestamp": (NOW-timedelta(seconds=40)).isoformat(),
                     "bid_price": 4.2, "ask_price": 4.3}}
    assert rank_contracts(
        "SPY", "CALL", [candidate], spot=753, now=NOW
    )["candidates"] == []
    candidate["open_interest_date"] = "2026-10-28"
    result = rank_contracts("SPY", "CALL", [candidate], spot=753, now=NOW)
    assert len(result["candidates"]) == 1
    assert result["execution_ready"] is False


def test_private_owner_message_is_research_not_a_broker_order():
    r = {"status": "PRIVATE_RESEARCH_SCAN", "completed": 1,
         "research_watches": 1,
         "_private_cards": [{
             "symbol": "SPY", "direction_research": "PUT",
             "levels": {"previous_day_high": 770, "previous_day_low": 766,
                        "opening_range_30m_high": 760, "opening_range_30m_low": 757},
             "contract": CODE, "delta": -.45, "gamma": .03,
             "oi_date": "2026-10-28",
             "history": {"last_delayed_close": 2.3,
                         "last_completed_bar_end": NOW.isoformat(),
                         "latest_session_observed_volume_partial": 2400}
         }]}
    text = private.owner_report(r)
    assert "SPY" in text and "OPRA متأخر" in text
    assert "جزئي" in text and "لا توجد توصيات تنفيذ" in text
    assert "\\n" not in text


def test_output_policy_denies_public_option_redistribution():
    from options_radar.output_policy import decide
    assert not decide("alpaca_indicative_options", "telegram_public", {}).allowed
    assert not decide("alpaca_indicative_options", "publish_derived", {}).allowed
