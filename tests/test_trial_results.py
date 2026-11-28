"""Posted trial results: read, never judged beyond the posted analysis."""
from options_radar.trial_results import interpret, line_ar, summary


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


def test_without_p_value_the_ratio_ci_decides_wording():
    """NCT05136677 as posted 2026-11-27: OS hazard ratio 0.62, 95 % CI 0.36-1.07, no p-value."""
    study = _study(p=None)
    analysis = study["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][0]["analyses"][0]
    analysis.update(paramValue="0.62", ciLowerLimit="0.36", ciUpperLimit="1.07")
    out = interpret(study)
    assert out["status"] == "PRIMARY_CI_INCLUDES_NO_EFFECT"
    assert out["primary"][0]["analyses"][0]["ci_includes_no_effect"] is True


def test_bmy_template_line_never_claims_significance_or_a_financial_effect():
    study = _study(p=None)
    analysis = study["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][0]["analyses"][0]
    analysis.update(paramValue="0.62", ciLowerLimit="0.36", ciUpperLimit="1.07")
    s = summary(interpret(study))
    assert s["financial_effect"] == "NOT_INFERRED" and s["ci"] == ["0.36", "1.07"]
    line = line_ar(s)
    assert "0.62" in line and "0.36–1.07" in line and "p: غير منشورة" in line and "2026-01-10" in line
    assert "تشمل «لا أثر»" in line and "لا يُستنتج أثر مالي" in line and "دال إحصائياً وفق" not in line


def test_results_event_in_the_registry_feed_carries_the_interpretation():
    from datetime import date

    from scripts import build_clinical_registry_feed as feed

    study = _study(p=None)
    study["protocolSection"]["sponsorCollaboratorsModule"]["leadSponsor"]["class"] = "INDUSTRY"
    study["protocolSection"]["statusModule"].update(
        resultsFirstPostDateStruct={"date": "2026-11-27", "type": "ACTUAL"},
        lastUpdatePostDateStruct={"date": "2026-11-27"})
    analysis = study["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][0]["analyses"][0]
    analysis.update(paramValue="0.62", ciLowerLimit="0.36", ciUpperLimit="1.07")
    index = feed._names.build_name_index({"BMY": ["Bristol-Myers Squibb"]})
    event = feed.study_event(study, index, start=date(2026, 11, 20), end=date(2026, 11, 28))
    assert event["kind"] == "TRIAL_RESULTS_POSTED" and event["symbol"] == "BMY"
    assert event["result_interpretation"]["status"] == "PRIMARY_CI_INCLUDES_NO_EFFECT"
    assert "لا تُعلن دلالة" in event["label"] and event["outcome_direction"] == "NOT_INFERRED"
