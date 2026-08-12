from options_radar.event_source_policy import (
    classify_source,
    cluster_evidence_summary,
    event_source_evidence,
)


def _event(source: str, category: str, url: str = "") -> dict:
    return {
        "source": source,
        "url": url,
        "category_normalized": category,
    }


def test_sec_and_fda_are_official_tier_a_sources():
    sec = classify_source("SEC EDGAR Precision Full-Text")
    fda = classify_source("Drugs@FDA", "https://www.fda.gov/example")
    assert sec.tier == "A_OFFICIAL"
    assert fda.tier == "A_OFFICIAL"
    assert sec.primary is True
    assert fda.primary is True


def test_attention_sources_cannot_establish_catalyst():
    for source in ("Finviz", "Reddit", "X API", "Stocktwits"):
        evidence = event_source_evidence(_event(source, "MERGER_DEFINITIVE"))
        assert evidence["attention_only"] is True
        assert evidence["can_establish_cause"] is False
        assert evidence["verification_state"] == "ATTENTION_ONLY"


def test_clinicaltrials_registry_does_not_prove_positive_readout():
    evidence = event_source_evidence(
        _event("ClinicalTrials.gov", "TRIAL_POSITIVE", "https://clinicaltrials.gov/study/NCT00000000")
    )
    assert evidence["source_official"] is True
    assert evidence["source_tier"] == "B_OFFICIAL_REGISTRY"
    assert evidence["can_establish_cause"] is False
    assert evidence["verification_state"] == "OFFICIAL_REGISTRY_ONLY"


def test_sec_variants_count_as_one_independent_family():
    summary = cluster_evidence_summary(
        [
            _event("SEC EDGAR", "MERGER_DEFINITIVE"),
            _event("SEC EDGAR Precision Full-Text", "MERGER_DEFINITIVE"),
        ]
    )
    assert summary["official_confirmed"] is True
    assert summary["independent_confirmation_count"] == 1
    assert summary["independent_confirmation_families"] == ["sec"]


def test_social_plus_aggregator_is_not_official_confirmation():
    summary = cluster_evidence_summary(
        [
            _event("Reddit", "PARTNERSHIP"),
            _event("Yahoo Finance News", "PARTNERSHIP"),
        ]
    )
    assert summary["official_confirmed"] is False
    assert summary["primary_cause_eligible"] is False
    assert summary["independent_confirmation_count"] == 0


def test_sec_plus_reuters_has_one_official_and_two_independent_families():
    summary = cluster_evidence_summary(
        [
            _event("SEC EDGAR", "MERGER_DEFINITIVE"),
            _event("Reuters", "MERGER_DEFINITIVE"),
        ]
    )
    assert summary["official_confirmed"] is True
    assert summary["primary_cause_eligible"] is True
    assert summary["independent_confirmation_count"] == 2
