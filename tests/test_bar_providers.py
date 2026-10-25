"""Alpaca bar provider: policy before any request, delay held, pagination, no partial history."""
from datetime import datetime, timedelta, timezone

from options_radar.bar_providers import AlpacaBars

NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)
ENV = {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true"}


class Session:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(dict(params))
        status, payload = self.pages.pop(0)
        return type("R", (), {"status_code": status, "json": lambda self: payload})()


ROW = {"t": "2026-10-26T13:30:00Z", "o": 1.0, "h": 1.2, "l": 0.9, "c": 1.1, "v": 10}


def test_no_request_without_policy_or_keys():
    session = Session([])
    assert AlpacaBars({}, session, NOW).bars("SPY", "5m", NOW - timedelta(days=1), NOW)["status"] == "DENIED_BY_POLICY"
    keyless = {"ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true"}
    assert AlpacaBars(keyless, session, NOW).bars("SPY", "5m", NOW - timedelta(days=1), NOW)["status"] == "CREDENTIALS_MISSING"
    assert session.calls == []


def test_pages_are_joined_and_the_latest_minutes_never_requested():
    session = Session([(200, {"bars": [ROW], "next_page_token": "p2"}), (200, {"bars": [ROW], "next_page_token": None})])
    got = AlpacaBars(ENV, session, NOW).bars("SPY", "5m", NOW - timedelta(days=1), NOW)
    assert got["status"] == "OK" and len(got["bars"]) == 2
    assert session.calls[1]["page_token"] == "p2"
    assert datetime.fromisoformat(session.calls[0]["end"]) == NOW - timedelta(minutes=16)


def test_errors_and_truncation_yield_no_bars():
    refused = Session([(403, {}), (403, {})])
    got = AlpacaBars(ENV, refused, NOW).bars("SPY", "1d", NOW - timedelta(days=9), NOW)
    assert got["status"] == "HTTP_403" and [c["feed"] for c in refused.calls] == ["sip", "iex"]
    bad = Session([(200, {"bars": [{**ROW, "o": "1"}]})])
    assert AlpacaBars(ENV, bad, NOW).bars("SPY", "1d", NOW - timedelta(days=9), NOW)["status"] == "MALFORMED"
    endless = Session([(200, {"bars": [ROW], "next_page_token": "x"})] * 12)
    got = AlpacaBars(ENV, endless, NOW).bars("SPY", "5m", NOW - timedelta(days=9), NOW)
    assert got["status"] == "TRUNCATED" and got["bars"] == []
    assert AlpacaBars(ENV, Session([]), NOW).bars("bad sym", "5m", NOW - timedelta(days=1), NOW)["status"] == "INVALID_REQUEST"


def test_sip_refusal_falls_back_to_iex_and_says_so():
    session = Session([(403, {}), (200, {"bars": [ROW], "next_page_token": None})])
    got = AlpacaBars(ENV, session, NOW).bars("SPY", "5m", NOW - timedelta(days=1), NOW)
    assert got["status"] == "OK" and got["feed"] == "iex" and got["coverage"].startswith("IEX")
    session = Session([(200, {"bars": [ROW], "next_page_token": None})])
    got = AlpacaBars(ENV, session, NOW).bars("SPY", "5m", NOW - timedelta(days=1), NOW)
    assert got["feed"] == "sip" and got["coverage"].startswith("SIP")
    forced = Session([(200, {"bars": [ROW], "next_page_token": None})])
    AlpacaBars({**ENV, "ALPACA_BARS_FEED": "iex"}, forced, NOW).bars("SPY", "5m", NOW - timedelta(days=1), NOW)
    assert forced.calls[0]["feed"] == "iex"


def test_multi_symbol_batches_survive_a_failed_batch():
    pages = [(200, {"bars": {"AAA": [ROW]}, "next_page_token": None}), (500, {}), (500, {})]
    got = AlpacaBars(ENV, Session(pages), NOW).multi_bars(["AAA", "BBB"], "1d", NOW - timedelta(days=9), NOW, batch=1)
    assert got["status"] == "OK" and got["batches"] == 2 and got["failed_batches"] == 1
    assert list(got["bars"]) == ["AAA"] and got["feed"] == {"AAA": "sip"}


def test_snapshots_and_assets_parse_and_filter():
    snap = {"AAA": {"dailyBar": {"v": 1000}, "prevDailyBar": {"c": 10.0}, "latestTrade": {"p": 11.0, "t": "2026-10-26T15:00:00Z"}},
            "BAD": {"dailyBar": None}}
    got = AlpacaBars(ENV, Session([(200, snap)]), NOW).snapshots(["AAA", "BAD"])
    assert got["snapshots"] == {"AAA": {"price": 11.0, "trade_time": "2026-10-26T15:00:00Z", "prev_close": 10.0,
                                        "day_volume_iex": 1000.0}} and got["coverage"].startswith("IEX")
    assets = [{"symbol": "AAA", "tradable": True, "exchange": "NASDAQ"},
              {"symbol": "OTCX", "tradable": True, "exchange": "OTC"},
              {"symbol": "NOPE", "tradable": False, "exchange": "NYSE"},
              {"symbol": "AB/CD", "tradable": True, "exchange": "NYSE"}]
    got = AlpacaBars(ENV, Session([(401, {}), (200, assets)]), NOW).assets()  # paper host refuses, live host answers
    assert got["status"] == "OK" and got["symbols"] == ["AAA"]
    assert got["excluded"] == {"OTC_OR_OTHER_VENUE": 1, "NOT_TRADABLE": 1, "SYMBOL_FORMAT": 1}

