from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

import scripts.run_classical_direction_radar as radar


NOW = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
HEADER = {"Last-Modified": "Wed, 14 Oct 2026 13:00:00 GMT"}


class Response:
    def __init__(self, *, text, headers=None):
        self.text = text
        self.headers = headers if headers is not None else HEADER

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, response):
        self.response = response

    def get(self, url, *, timeout):
        assert url == radar.CBOE_C1_UNDERLYINGS
        assert timeout <= 30
        return self.response


def _csv():
    # Minimum-file-size guard prevents HTML/block pages and malformed responses.
    others = "".join(f"T{i:03d},TEST{i}\n" for i in range(140))
    return "Symbol,Company\nMU,MICRON\nAAPL,APPLE\n" + others


def test_fresh_official_cboe_directory_yields_verified_exchange_underlyings():
    symbols, modified, error = radar._official_cboe_underlyings(
        session=FakeSession(Response(text=_csv())), now=NOW
    )
    assert error is None
    assert "MU" in symbols and "AAPL" in symbols
    assert len(symbols) >= 100
    assert modified.startswith("2026-10-14T13:00")


def test_stale_or_unverifiable_cboe_directory_fails_closed():
    for response in (
        Response(text=_csv(), headers={}),
        Response(text=_csv(), headers={"Last-Modified": "Tue, 01 Sep 2026 13:00:00 GMT"}),
        Response(text="<html>blocked</html>"),
    ):
        symbols, modified, error = radar._official_cboe_underlyings(
            session=FakeSession(response), now=NOW
        )
        assert symbols == set()
        assert modified is None
        assert error


def test_only_listed_underlyings_enter_classical_radar_when_occ_down(monkeypatch, tmp_path):
    monkeypatch.setenv("CLASSICAL_DIRECTION_SYMBOLS", "MU,AAPL,TSLA")
    class Universe:
        official_verified = False
        official_symbols = []
        source = "OCC unavailable"
        cache_used = False
        errors = {"occ:EU": "HTTPError: 520", "occ:IU": "HTTPError: 520"}
    monkeypatch.setattr(
        radar.IndependentOptionableUniverse,
        "build",
        lambda self, *args, **kwargs: Universe(),
    )
    monkeypatch.setattr(
        radar, "_official_cboe_underlyings",
        lambda: ({"MU", "AAPL"}, "2026-10-14T13:00:00+00:00", None),
    )
    index = pd.date_range("2026-10-14 13:30:00+00:00", periods=20, freq="15min")
    frame = pd.DataFrame(
        {"Close": [100.] * len(index), "Volume": [1_000_000.] * len(index)},
        index=index,
    )
    monkeypatch.setattr(
        radar, "_fetch_all_frames",
        lambda symbols, settings: (
            {s: {"daily": frame, "intraday": frame, "hourly": frame,
                 "sources": {"daily": "test", "intraday": "test"},
                 "freshness": {"daily": "test", "intraday": "test"}} for s in symbols},
            {},
        ),
    )
    monkeypatch.setattr(radar, "_avg_dollar_volume", lambda *args, **kwargs: 200_000_000.)
    monkeypatch.setattr(
        radar, "build_direction",
        lambda symbol, *args: SimpleNamespace(as_dict=lambda: {
            "symbol": symbol, "decision": "WAIT", "agreement_score": 0,
        }),
    )
    result = radar.run(output_path=tmp_path / "test.json", max_symbols=12)
    assert result["summary"]["occ_optionability_verified"] is False
    assert result["summary"]["cboe_optionability_verified"] is True
    assert result["summary"]["companies_verified"] == 2
    assert result["summary"]["operational_status"] == "READY"
    assert {row["symbol"] for row in result["waits"]} == {"MU", "AAPL"}
    assert not result["signals"]
    assert all(not row["optionability_verified_by_occ"] for row in result["waits"])
    assert all(row["optionability_verified_by_cboe"] for row in result["waits"])
