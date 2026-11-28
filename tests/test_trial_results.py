"""Posted trial results: read, never judged beyond the posted analysis."""
from options_radar.trial_results import interpret


def _study(p="0.003", comment="", has=True):
    return {"protocolSection": {"identificationModule": {"nctId": "NCT05136677", "briefTitle": "X"},
                                "statusModule": {"overallStatus": "COMPLETED",
                                                 "resultsFirstPostDateStruct": {"date": "2026-01-10"}},
                                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Bristol-Myers Squibb"}}},
            "hasResults": has,
            "resultsSection": {"outcomeMeasuresModule": {"outcomeMeasures": [
                {"type": "PRIMARY", "title": "PFS", "analyses": [
                    {"statisticalMethod": "Log Rank", "pValue": p, "paramType": "Hazard Ratio (HR)", "paramValue": "0.72",
                     "ciLowerLimit": "0.6", "ciUpperLimit": "0.86", "ciPctValue": "95", "statisticalComment": comment}]},
                {"type": "SECONDARY", "title": "OS", "analyses": [{"pValue": "0.2"}]}]}}}


def test_significant_primary_is_reported_as_per_posted_analysis_only():
    out = interpret(_study())
    assert out["status"] == "PRIMARY_SIGNIFICANT_PER_POSTED_ANALYSIS" and len(out["primary"]) == 1
    a = out["primary"][0]["analyses"][0]
    assert a["p_value_as_posted"] == "0.003" and a["threshold_basis"] == "default 0.05" and a["estimate"] == "0.72"


def test_stated_threshold_and_inequality_p_values():
    out = interpret(_study(p="0.03", comment="Two-sided alpha of 0.025 was allocated"))
    assert out["status"] == "PRIMARY_NOT_SIGNIFICANT_PER_POSTED_ANALYSIS"
    assert out["primary"][0]["analyses"][0]["threshold"] == 0.025
    assert interpret(_study(p="<0.0001"))["status"] == "PRIMARY_SIGNIFICANT_PER_POSTED_ANALYSIS"
    assert interpret(_study(p=">0.05"))["status"] == "PRIMARY_NOT_SIGNIFICANT_PER_POSTED_ANALYSIS"


def test_no_results_posted():
    out = interpret(_study(has=False))
    assert out["status"] == "NO_RESULTS_POSTED" and out["source"].endswith("NCT05136677")
