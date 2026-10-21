"""Offline evidence-gate tests for the independently implemented gamma heatmap."""
import math

import pytest

from options_radar.gamma_heatmap_research import build_gamma_heatmap_research


def sample():
    return {
        "symbol": "EXAMPLE",
        "spot": 100.0,
        "gamma_coverage_pct": 100.0,
        "oi_coverage_pct": 100.0,
        "data_tier": "research",
        "call_wall": 105.0,
        "put_wall": 95.0,
        "by_strike": [
            {"strike": 105.0, "call_gex_proxy": 400.0, "put_gex_proxy": 30.0, "total_oi": 1200.0},
            {"strike": 95.0, "call_gex_proxy": 30.0, "put_gex_proxy": 300.0, "total_oi": 900.0},
            {"strike": 100.0, "call_gex_proxy": 100.0, "put_gex_proxy": 100.0, "total_oi": 600.0},
        ],
    }


def test_signed_heatmap_is_derived_without_dealer_claims():
    result = build_gamma_heatmap_research(sample())
    assert result["available"] is True
    assert result["status"] == "RESEARCH_ONLY"
    assert result["gross_gex_proxy"] == 960.0
    assert result["levels_shown"] == 3
    assert [row["strike"] for row in result["levels"]] == [95.0, 100.0, 105.0]
    assert result["levels"][0]["signed_gex_proxy"] == -270.0
    assert result["levels"][-1]["signed_gex_proxy"] == 370.0
    assert result["levels"][-1]["call_wall"] is True
    assert result["levels"][0]["put_wall"] is True
    assert sum(x["gross_share_pct"] for x in result["levels"]) == pytest.approx(100, abs=0.02)
    assert result["dealer_inventory_verified"] is False
    assert result["display_authorized"] is False
    assert result["execution_grade"] is False
    assert result["gamma_flip_model_confirmed"] is False


def test_heatmap_top_n_limits_output_without_changing_denominator():
    result = build_gamma_heatmap_research(sample(), maximum_levels=2)
    assert result["strikes_seen"] == 3
    assert result["levels_shown"] == 2
    assert result["gross_gex_proxy"] == 960.0


@pytest.mark.parametrize("value,reason", [
    (None, "missing_gamma_map"),
    ({"spot": None, "by_strike": []}, "missing_spot"),
    ({"spot": 100.0, "by_strike": []}, "missing_or_excessive_strikes"),
])
def test_missing_input_is_not_promoted(value, reason):
    report = build_gamma_heatmap_research(value)
    assert report["available"] is False
    assert report["reason"] == reason
    assert report["levels"] == []


def test_invalid_and_duplicate_exposures_fail_closed():
    original = sample()
    original["by_strike"].append(original["by_strike"][0])
    assert build_gamma_heatmap_research(original)["reason"] == "invalid_or_duplicate_strike"
    original = sample()
    original["by_strike"][0]["call_gex_proxy"] = math.nan
    assert build_gamma_heatmap_research(original)["available"] is False
    original = sample()
    original["by_strike"][0]["put_gex_proxy"] = -1
    assert build_gamma_heatmap_research(original)["available"] is False


def test_no_gamma_is_not_a_heatmap_and_coverage_warning_is_not_a_ban():
    data = sample()
    data["by_strike"][0]["call_gex_proxy"] = 0
    data["by_strike"][0]["put_gex_proxy"] = 0
    data["by_strike"][1]["call_gex_proxy"] = 0
    data["by_strike"][1]["put_gex_proxy"] = 0
    data["by_strike"][2]["call_gex_proxy"] = 0
    data["by_strike"][2]["put_gex_proxy"] = 0
    assert build_gamma_heatmap_research(data)["reason"] == "no_calculable_gamma"
    data = sample()
    data["gamma_coverage_pct"] = 25.0
    report = build_gamma_heatmap_research(data)
    assert report["available"] is True
    assert report["coverage_warning"] is True
    assert report["research_only"] is True


def test_level_bounds():
    with pytest.raises(ValueError):
        build_gamma_heatmap_research(sample(), maximum_levels=0)
