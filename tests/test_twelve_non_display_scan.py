"""Twelve Data independent research: fixed-budget, owner-only and no-display."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import run_twelve_non_display_scan as td

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 30, 19, 15, tzinfo=timezone.utc)
ENV = {"TWELVE_DATA_API_KEY": "SECRET_EXAMPLE_KEY",
       "TWELVE_DATA_NON_DISPLAY_USE_AUTHORIZED": "true",
       "DATA_TERMS_CONFIRMED": "twelve_data"}


class Reply:
    def __init__(self, data):
        self.status_code = 200
        self.data = data
        self.content = json.dumps(data).encode()
    def json(self):
        return self.data


class TwelveFixture:
    def __init__(self):
        self.calls = []
    def get(self, url, params, headers, timeout, allow_redirects):
        assert url == "https://api.twelvedata.com/time_series"
        assert params["interval"] == "5min"
        assert params["outputsize"] <= 600
        assert params["timezone"] == "America/New_York"
        self.calls.append(params["symbol"])
        rows = []
        for day in (28, 29, 30):
            start = datetime(2026, 10, day, 9, 30, tzinfo=NY)
            for i in range(78):
                # Realistic, complete RTH 5m candles in provider NY clock time.
                val = 700 + .02 * i + (day - 28) * .5
                rows.append({
                    "datetime": (start + timedelta(minutes=5*i)).strftime("%Y-%m-%d %H:%M:%S"),
                    "open": str(val), "high": str(val + .12), "low": str(val - .1),
                    "close": str(val + .02), "volume": "10000"})
        return Reply({"status": "ok",
                      "meta": {"symbol": params["symbol"], "interval": "5min"},
                      "values": rows[::-1]})


def test_without_owner_permission_uses_zero_credits():
    class Forbidden:
        def get(self, *_args, **_kwargs):
            raise AssertionError("Never call the provider without its terms confirmation")
    no = td.run({}, now=NOW, session=Forbidden())
    assert no["status"] == "NO_KEY" and no["requests"] == 0
    blocked = td.run({"TWELVE_DATA_API_KEY": "secret"}, now=NOW, session=Forbidden())
    assert blocked["status"] == "OWNER_TERMS_NOT_CONFIRMED"
    assert blocked["requests"] == 0


def test_realistic_five_minute_private_research_covers_all_core_symbols():
    fixture = TwelveFixture()
    pauses = []
    report = td.run(ENV, now=NOW, session=fixture, sleep=pauses.append)
    assert report["status"] == "NON_DISPLAY_LEVELS_COMPUTED"
    assert report["symbols_requested"] == 11
    assert report["symbols_with_bars"] == 11
    assert report["symbols_with_computed_levels"] == 11
    assert report["requests"] == 11
    assert report["rate_limit_reserved_credits"] == 11
    assert len(pauses) == 10 and all(p == 12 for p in pauses)
    assert fixture.calls[:2] == ["SPY", "QQQ"]
    assert "BABA" in fixture.calls and "GOOG" in fixture.calls
    assert report["execution_authority"] is False
    assert report["telegram_delivery_allowed"] is False
    assert report["public_display_allowed"] is False
    serialized = json.dumps(report)
    for data in ("SECRET_EXAMPLE_KEY", "700.02", "713.22", "opening_range",
                 "vwap_5m_iex", '"decision":', '"last_completed_5m_close":'):
        assert data not in serialized


def test_duplicate_or_unfinished_candles_are_not_accepted():
    fixture = TwelveFixture()
    raw = fixture.get("https://api.twelvedata.com/time_series",
                      params={"symbol": "SPY", "interval": "5min",
                              "outputsize": 600, "timezone": "America/New_York"},
                      headers={}, timeout=12, allow_redirects=False).json()
    candles = td._parse_bars(raw, "SPY", now=NOW)
    assert candles and len(candles) <= len(raw["values"])
    # A future, unfinished 5m provider candle must not be treated as finished.
    raw["values"].append({"datetime": "2026-10-30 15:15:00",
                          "open": "900", "high": "901", "low": "899",
                          "close": "900", "volume": "99999"})
    candles2 = td._parse_bars(raw, "SPY", now=NOW)
    assert all(x["high"] < 901 for x in candles2)


def test_bad_meta_and_negative_prices_reject_whole_symbol():
    data = TwelveFixture().get("https://api.twelvedata.com/time_series",
             params={"symbol": "SPY", "interval": "5min",
                     "outputsize": 600, "timezone": "America/New_York"},
             headers={}, timeout=12, allow_redirects=False).json()
    assert td._parse_bars(data, "QQQ", now=NOW) == []
    data["values"][0]["close"] = "-15"
    assert td._parse_bars(data, "SPY", now=NOW) == []


def test_workflow_is_independent_of_alpaca_approval():
    wf = (Path(".github/workflows/private-market-scan.yml")
          .read_text(encoding="utf-8"))
    assert "twelve-non-display:" in wf
    section = wf.split("  twelve-non-display:", 1)[1]
    assert "vars.TWELVE_DATA_NON_DISPLAY_USE_AUTHORIZED == 'true'" in section
    assert "python -m scripts.run_twelve_non_display_scan" in section
    assert "vars.ALPACA_INTERNAL_DATA_USE_AUTHORIZED" not in section
    assert "$RUNNER_TEMP/twelve_non_display_health.json" in section
    assert "upload-artifact" not in section and "git add" not in section


def test_incomplete_previous_day_is_not_relabelled_as_full_day_high_low():
    fixture = TwelveFixture()
    raw = fixture.get("https://api.twelvedata.com/time_series",
                      params={"symbol": "SPY", "interval": "5min",
                              "outputsize": 600, "timezone": "America/New_York"},
                      headers={}, timeout=12, allow_redirects=False).json()
    # Remove every afternoon bar on Oct 29, so the source has only morning data.
    raw["values"] = [r for r in raw["values"]
                     if not (r["datetime"].startswith("2026-10-29")
                             and r["datetime"][11:] >= "12:00:00")]
    intraday = td._parse_bars(raw, "SPY", now=NOW)
    daily = td._daily_from_intraday(intraday)
    assert all(row["timestamp"][:10] != "2026-10-29" for row in daily)
    assert any(row["timestamp"][:10] == "2026-10-28" for row in daily)
