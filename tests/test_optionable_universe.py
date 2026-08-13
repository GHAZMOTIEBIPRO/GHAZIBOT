from __future__ import annotations

import json

import requests

from options_radar.optionable_universe import (
    IndependentOptionableUniverse,
    _walk_cboe_active,
    parse_occ_dlp_text,
)


def test_parse_occ_dlp_supports_pipe_and_deduplicates():
    text = """Option Symbol|Underlying Symbol|Symbol Name|Exchanges|Product Type
AAPL|AAPL|APPLE INC|CBOE,NSDQ|EU
AAPL|AAPL|APPLE INC|CBOE,NSDQ|EU
SPY|SPY|SPDR S&P 500 ETF|CBOE|EU
"""
    rows = parse_occ_dlp_text(text)
    assert [row["underlying_symbol"] for row in rows] == ["AAPL", "SPY"]
    assert rows[0]["option_symbol"] == "AAPL"


def test_parse_occ_dlp_supports_tab_layout():
    text = "OS\tUS\tSN\tEXCH\tONN\nNVDA\tNVDA\tNVIDIA CORP\tCBOE\tEU\n"
    rows = parse_occ_dlp_text(text)
    assert rows == [
        {
            "option_symbol": "NVDA",
            "underlying_symbol": "NVDA",
            "symbol_name": "NVIDIA CORP",
            "exchanges": "CBOE",
            "product_type": "EU",
        }
    ]


def test_cboe_walker_extracts_contract_underlyings_and_aliases():
    payload = {
        "categories": [
            {
                "category": "all",
                "calls": [
                    {"symbol": "SPXW", "expires": "2026-08-14", "strike": 6500, "volume": 1000},
                    {"symbol": "NVDA", "expires": "2026-08-14", "strike": 200, "volume": 900},
                ],
                "puts": [
                    {"symbol": "QQQ", "expires": "2026-08-14", "strike": 600, "volume": 800}
                ],
            }
        ]
    }
    rows = _walk_cboe_active(payload)
    assert [row["symbol"] for row in rows] == ["SPX", "NVDA", "QQQ"]


class _Response:
    def __init__(self, *, text: str = "", payload=None, status_code: int = 200):
        self.text = text
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self._payload


class _Session:
    def __init__(self, occ_text: str, cboe_payload: dict | None = None, fail_occ: bool = False):
        self.headers = {}
        self.occ_text = occ_text
        self.cboe_payload = cboe_payload or {}
        self.fail_occ = fail_occ

    def get(self, url, params=None, headers=None, timeout=None):
        del headers, timeout
        if "delo-download" in url:
            if self.fail_occ:
                raise requests.ConnectionError("OCC down")
            return _Response(text=self.occ_text)
        if "most_active" in url:
            return _Response(payload=self.cboe_payload)
        raise AssertionError(url)


def test_builder_is_independent_from_stock_ranking_and_occ_filters(tmp_path):
    occ = """OS|US|SN|EXCH|ONN
AAPL|AAPL|APPLE|CBOE|EU
NVDA|NVDA|NVIDIA|CBOE|EU
SPY|SPY|SPY ETF|CBOE|EU
"""
    cboe = {
        "categories": [
            {"calls": [{"symbol": "NVDA", "expires": "2026-08-14", "strike": 200, "volume": 5000}]}
        ]
    }
    builder = IndependentOptionableUniverse(
        session=_Session(occ, cboe), cache_path=tmp_path / "occ.json"
    )
    result = builder.build(["AAPL", "NOOPTION", "NVDA", "SPY"], max_symbols=10)

    assert result.official_verified is True
    assert result.symbols[:3] == ["NVDA", "SPY", "AAPL"]
    assert "NOOPTION" not in result.symbols
    assert result.attention_symbols == ["NVDA"]
    assert result.occ_rows == 6  # EU and IU fixture calls are deliberately both accepted


def test_builder_uses_official_cache_when_occ_temporarily_fails(tmp_path):
    cache = tmp_path / "occ.json"
    cache.write_text(
        json.dumps(
            {
                "source": "OCC Directory of Listed Products",
                "official": True,
                "product_types": ["EU"],
                "symbols": ["AAPL", "SPY"],
                "rows": [
                    {"option_symbol": "AAPL", "underlying_symbol": "AAPL"},
                    {"option_symbol": "SPY", "underlying_symbol": "SPY"},
                ],
            }
        ),
        encoding="utf-8",
    )
    builder = IndependentOptionableUniverse(
        session=_Session("", fail_occ=True), cache_path=cache
    )
    result = builder.build(["AAPL", "TSLA", "SPY"], max_symbols=10, include_cboe_attention=False)

    assert result.official_verified is True
    assert result.cache_used is True
    assert result.symbols == ["SPY", "AAPL"]
    assert "TSLA" not in result.symbols
    assert result.errors["occ:EU"].startswith("ConnectionError")


def test_builder_fails_honestly_without_occ_or_cache(tmp_path):
    builder = IndependentOptionableUniverse(
        session=_Session("", fail_occ=True), cache_path=tmp_path / "missing.json"
    )
    result = builder.build(["NVDA", "AAPL"], max_symbols=10, include_cboe_attention=False)

    assert result.official_verified is False
    assert result.symbols[:2] == ["NVDA", "AAPL"]
    assert "OCC verification unavailable" in result.source
    assert any("not officially verified" in item for item in result.limitations)
