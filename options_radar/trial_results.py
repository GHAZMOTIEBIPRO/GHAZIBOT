"""Read the results a sponsor POSTED on ClinicalTrials.gov (API v2) - no judgement beyond the posting.

For each primary outcome: title, posted statistical analyses (method, p-value as written, estimate type
and value, confidence interval) and whether the posted p-value is below the analysis' own stated
significance threshold when one is given (else 0.05, labelled as the default). A p-value under the
threshold is "statistically significant per the posted analysis" - not "trial success", not a price
direction. No p-value but a ratio estimate with its CI (hazard/odds/risk ratio) -> whether the CI includes 1
(the no-effect value). No posted results -> status NO_RESULTS_POSTED with the dates that are known.
"""
from __future__ import annotations

import re
from typing import Any

_P = re.compile(r"^\s*([<>]=?|=)?\s*([0-9]*\.?[0-9]+(?:[eE]-?\d+)?)\s*$")


def _p(value: Any) -> tuple[str | None, float | None]:
    m = _P.match(str(value or ""))
    return (m.group(1) or "=", float(m.group(2))) if m else (None, None)


def interpret(study: dict[str, Any]) -> dict[str, Any]:
    ps = study.get("protocolSection") or {}
    ident, status = ps.get("identificationModule") or {}, ps.get("statusModule") or {}
    base = {"nct_id": ident.get("nctId"), "title": ident.get("briefTitle"),
            "sponsor": ((ps.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name"),
            "phases": (ps.get("designModule") or {}).get("phases"), "overall_status": status.get("overallStatus"),
            "primary_completion": (status.get("primaryCompletionDateStruct") or {}).get("date"),
            "results_first_posted": (status.get("resultsFirstPostDateStruct") or {}).get("date"),
            "source": f"https://clinicaltrials.gov/study/{ident.get('nctId')}"}
    measures = (((study.get("resultsSection") or {}).get("outcomeMeasuresModule") or {}).get("outcomeMeasures")) or []
    if not study.get("hasResults") or not measures:
        return {**base, "status": "NO_RESULTS_POSTED", "primary": []}
    primary = []
    for om in measures:
        if om.get("type") != "PRIMARY":
            continue
        analyses = []
        for a in om.get("analyses") or []:
            op, p = _p(a.get("pValue"))
            stated = a.get("statisticalComment") or ""
            threshold = 0.05
            m = re.search(r"(?:alpha|significance level|significance)\D{0,20}(0?\.\d+)", stated, re.IGNORECASE)
            if m:
                threshold = float(m.group(1))
            below = None if p is None else (p < threshold if op in ("=", "<", "<=") else False)
            ci_null = None
            if any(k in str(a.get("paramType") or "") for k in ("Ratio", "ratio")):
                try:
                    lo, hi = float(a.get("ciLowerLimit")), float(a.get("ciUpperLimit"))
                    ci_null = lo <= 1.0 <= hi  # a ratio's no-effect value is 1
                except (TypeError, ValueError):
                    ci_null = None
            analyses.append({"method": a.get("statisticalMethod"), "p_value_as_posted": a.get("pValue"),
                             "ci_includes_no_effect": ci_null,
                             "estimate_type": a.get("paramType"), "estimate": a.get("paramValue"),
                             "ci": [a.get("ciLowerLimit"), a.get("ciUpperLimit")], "ci_percent": a.get("ciPctValue"),
                             "threshold": threshold, "threshold_basis": "stated" if m else "default 0.05",
                             "significant_per_posted_analysis": below})
        primary.append({"title": om.get("title"), "time_frame": om.get("timeFrame"), "analyses": analyses})
    any_sig = [a["significant_per_posted_analysis"] for o in primary for a in o["analyses"]
               if a["significant_per_posted_analysis"] is not None]
    ci_flags = [a["ci_includes_no_effect"] for o in primary for a in o["analyses"] if a["ci_includes_no_effect"] is not None]
    if not any_sig and ci_flags:
        # no p-value posted: the posted confidence interval is the only evidence
        verdict = ("PRIMARY_CI_INCLUDES_NO_EFFECT" if all(ci_flags) else "PRIMARY_CI_EXCLUDES_NO_EFFECT")
        return {**base, "status": verdict, "primary": primary}
    verdict = ("NO_POSTED_ANALYSIS" if not any_sig else
               "PRIMARY_SIGNIFICANT_PER_POSTED_ANALYSIS" if any(any_sig) else "PRIMARY_NOT_SIGNIFICANT_PER_POSTED_ANALYSIS")
    return {**base, "status": verdict, "primary": primary}
