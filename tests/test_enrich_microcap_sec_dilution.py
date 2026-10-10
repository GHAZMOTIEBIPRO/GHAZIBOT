from datetime import datetime, timezone

from scripts.enrich_microcap_sec_dilution import enrich, propagate_to_fast_payload


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Session:
    def get(self, url, **kwargs):
        if url.endswith("company_tickers.json"):
            return _Response(
                {
                    "0": {
                        "ticker": "MICR",
                        "cik_str": 1234567,
                        "title": "Micro Example Inc.",
                    }
                }
            )
        if "companyfacts/CIK0001234567.json" in url:
            return _Response(
                {
                    "facts": {
                        "dei": {
                            "EntityCommonStockSharesOutstanding": {
                                "units": {
                                    "shares": [
                                        {
                                            "val": 1_000_000,
                                            "end": "2026-01-01",
                                            "filed": "2026-01-05",
                                            "form": "10-K",
                                        },
                                        {
                                            "val": 2_000_000,
                                            "end": "2026-09-15",
                                            "filed": "2026-09-20",
                                            "form": "10-Q",
                                        },
                                    ]
                                }
                            }
                        }
                    }
                }
            )
        raise AssertionError(url)


def test_enrichment_updates_microcap_hunter_with_sec_dilution_risk():
    state = {
        "symbols": {
            "MICR": {
                "price": 4.0,
                "market_cap": 40_000_000,
                "float_shares": 2_000_000,
                "rvol": 4.0,
                "dollar_volume": 3_000_000,
                "day_move_pct": 5.0,
                "supply_score": 92,
                "catalyst_score": 82,
                "dilution_risk": 10,
                "microcap_hunter": {"score": 90, "stage": "PRIORITY"},
            }
        }
    }
    latest = {
        "omega": {
            "catalyst_intelligence": {
                "by_symbol": {
                    "MICR": {
                        "members": [
                            {
                                "form": "424B5",
                                "purpose": "dilution",
                                "event_date": "2026-10-07",
                                "event_value": 20_000_000,
                                "source": "SEC EDGAR",
                                "evidence": (
                                    "registered direct offering; warrants to purchase "
                                    "3,000,000 shares"
                                ),
                            }
                        ]
                    }
                }
            }
        }
    }

    result = enrich(
        state,
        latest,
        session=_Session(),
        maximum_symbols=5,
        now=datetime(2026, 10, 10, 16, 0, tzinfo=timezone.utc),
    )

    row = result["symbols"]["MICR"]
    assert row["sec_dilution_v2"]["available"] is True
    assert row["sec_dilution_v2"]["risk_score"] >= 90
    assert row["microcap_hunter"]["stage"] == "AVOID_RISK"
    assert "SEC_DILUTION_V2_HIGH" in row["microcap_hunter"]["flags"]
    assert result["sec_dilution_v2"]["enriched"] == 1
    assert result["sec_dilution_v2"]["decision_authority"] is False

def test_propagation_adds_research_fields_without_changing_fast_score_or_stage():
    state = {
        "sec_dilution_v2": {"research_only": True, "selected": 1},
        "symbols": {
            "MICR": {
                "sec_dilution_v2": {"risk_score": 88, "research_only": True},
                "microcap_hunter": {"score": 40, "stage": "AVOID_RISK"},
            }
        },
    }
    fast = {
        "top": [{"symbol": "MICR", "score": 91, "stage": "IGNITION"}],
        "actionable": [{"symbol": "MICR", "score": 91, "stage": "IGNITION"}],
    }

    result = propagate_to_fast_payload(state, fast)

    assert result["actionable"][0]["score"] == 91
    assert result["actionable"][0]["stage"] == "IGNITION"
    assert result["actionable"][0]["sec_dilution_v2"]["risk_score"] == 88
    assert result["actionable"][0]["microcap_hunter"]["stage"] == "AVOID_RISK"
    assert result["sec_dilution_v2_changes_live_score"] is False

