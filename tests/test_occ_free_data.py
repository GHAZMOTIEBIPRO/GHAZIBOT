from __future__ import annotations

from datetime import date
from typing import Any

import requests

from options_radar.occ_expiry_overlay import apply_occ_to_expiry_radar
from options_radar.occ_free_data import OccFreeVolumeClient, fetch_occ_contexts, parse_occ_volume_csv


def test_parse_occ_aggregate_columns() -> None:
    parsed = parse_occ_volume_csv(
        "Underlying,Call Volume,Put Volume,Total Volume\nAAPL,1200,800,2000\n"
    )
    assert parsed["call_volume"] == 1200
    assert parsed["put_volume"] == 800
    assert parsed["total_volume"] == 2000
    assert parsed["put_call_ratio"] == 0.6667


def test_parse_occ_side_rows() -> None:
    parsed = parse_occ_volume_csv(
        "Symbol,P or C,Contract Volume\nAAPL,C,450\nAAPL,P,900\n"
    )
    assert parsed["call_volume"] == 450
    assert parsed["put_volume"] == 900
    assert parsed["put_call_ratio"] == 2.0


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []

    def mount(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def get(self, _url: str, *, params: dict[str, Any], timeout: int) -> _Response:
        self.calls.append({"params": params, "timeout": timeout})
        return self.responses.pop(0)


def test_occ_client_falls_back_to_previous_business_date() -> None:
    session = _Session(
        [
            _Response(404),
            _Response(200, "Symbol,Call Volume,Put Volume\nAAPL,100,150\n"),
        ]
    )
    client = OccFreeVolumeClient(session=session, min_interval_seconds=0)
    result = client.fetch_report("AAPL", "daily", reference_date=date(2026, 7, 29))
    assert result["success"] is True
    assert result["call_volume"] == 100
    assert result["put_volume"] == 150
    assert len(session.calls) == 2
    assert session.calls[0]["params"]["reportDate"] == "20260729"
    assert session.calls[1]["params"]["reportDate"] == "20260728"


class _SelectiveOccClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def fetch_symbol(self, symbol: str, *, report_keys=None) -> dict[str, Any]:
        keys = tuple(sorted(report_keys or ("daily", "weekly", "monthly")))
        self.calls.append((symbol, keys))
        reports = {
            key: {
                "success": True,
                "source": "OCC Volume Query",
                "report_key": key,
                "report_date": "20260729",
                "call_volume": 100,
                "put_volume": 400,
                "total_volume": 500,
                "put_call_ratio": 4.0,
            }
            for key in keys
        }
        return {"symbol": symbol, "successful_reports": len(reports), "reports": reports}


def test_occ_context_fetch_funnel_skips_unneeded_reports_and_symbols() -> None:
    client = _SelectiveOccClient()
    contexts = fetch_occ_contexts(
        ["AAPL", "MSFT", "NVDA"],
        client=client,
        report_keys_by_symbol={
            "AAPL": {"weekly"},
            "MSFT": {"monthly", "weekly"},
        },
    )
    assert list(contexts) == ["AAPL", "MSFT"]
    assert client.calls == [
        ("AAPL", ("weekly",)),
        ("MSFT", ("monthly", "weekly")),
    ]
    assert set(contexts["AAPL"]["reports"]) == {"weekly"}
    assert set(contexts["MSFT"]["reports"]) == {"weekly", "monthly"}


class _OccClient:
    def fetch_symbol(self, symbol: str) -> dict[str, Any]:
        reports = {
            key: {
                "success": True,
                "source": "OCC Volume Query",
                "report_key": key,
                "report_date": "20260729",
                "call_volume": 100,
                "put_volume": 400,
                "total_volume": 500,
                "put_call_ratio": 4.0,
            }
            for key in ("daily", "weekly", "monthly")
        }
        return {"symbol": symbol, "successful_reports": 3, "reports": reports}


def test_occ_context_enriches_but_never_promotes_to_a() -> None:
    payload = {
        "stocks": [{"symbol": "AAPL"}],
        "expiry_radar": {
            "provider_audit": {"AAPL": {"success": True}},
            "profiles": {
                "daily": {
                    "calls": [],
                    "puts": [
                        {
                            "symbol": "AAPL",
                            "option_type": "put",
                            "opportunity_tier": "B",
                            "rank_score": 70.0,
                            "reasons": ["base"],
                        }
                    ],
                },
                "weekly": {"calls": [], "puts": []},
                "monthly": {"calls": [], "puts": []},
            },
            "summary": {},
            "policy": {},
        },
        "summary": {},
    }
    enriched = apply_occ_to_expiry_radar(payload, client=_OccClient())
    row = enriched["expiry_radar"]["profiles"]["daily"]["puts"][0]
    assert row["opportunity_tier"] == "B"
    assert row["occ_official_context"]["available"] is True
    assert row["occ_official_context"]["aligned_with_contract_side"] is True
    assert row["rank_score"] > 70.0
    assert any("OCC رسمي" in reason for reason in row["reasons"])
    assert enriched["expiry_radar"]["policy"]["occ_cannot_create_tier_a"] is True
    assert enriched["expiry_radar"]["summary"]["occ_requested_symbols"] == 1
    assert enriched["expiry_radar"]["summary"]["occ_requested_reports"] == 1
