from __future__ import annotations

from options_radar.phase61_policy import _upgrade_stocks


def _payload() -> dict:
    return {
        "stocks": [
            {
                "symbol": "AAPL",
                "score": 90,
                "new_stock_setup": True,
                "entry_state": "confirmed",
            }
        ],
        "stock_recommendations": [
            {
                "symbol": "AAPL",
                "decision": "مراقبة فقط",
                "confidence": 70,
                "confirmed_sources": ["Yahoo/yfinance market data"],
            }
        ],
    }


def test_finra_short_volume_cannot_promote_candidate_alone() -> None:
    payload = _payload()
    intelligence = {
        "stocks": {
            "AAPL": {
                "sources": ["FINRA Reg SHO"],
                "official_sources": ["FINRA Reg SHO"],
                "market_sources": [],
                "social_score": 0,
            }
        }
    }
    _upgrade_stocks(payload, intelligence)
    result = payload["stock_recommendations"][0]
    assert result["cross_source_confirmed"] is False
    assert "مشروط" not in result["decision"]
    assert result["supporting_context_sources"] == ["FINRA Reg SHO"]
    assert result["official_sources"] == []


def test_market_plus_directional_source_can_confirm_research_candidate() -> None:
    payload = _payload()
    payload["stock_recommendations"][0]["confirmed_sources"] = [
        "Yahoo/yfinance market data",
        "SEC 8-K",
    ]
    _upgrade_stocks(payload, {"stocks": {"AAPL": {}}})
    result = payload["stock_recommendations"][0]
    assert result["cross_source_confirmed"] is True
    assert "مرشح بحثي مشروط" in result["decision"]
