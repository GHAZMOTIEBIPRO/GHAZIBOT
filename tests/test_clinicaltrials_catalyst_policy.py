from options_radar.official_catalyst_intelligence import build_catalyst_intelligence


def _registry_event(headline: str, form: str, score: int):
    return {
        "symbol": "MRNA",
        "company": "Moderna Inc",
        "event_date": "2026-10-07",
        "category": (
            "ClinicalTrials results posted"
            if form == "REGISTRY_RESULTS"
            else "Clinical trial registry update"
        ),
        "headline": headline,
        "score": score,
        "source": "ClinicalTrials.gov",
        "form": form,
        "url": "https://clinicaltrials.gov/study/NCT12345678",
        "evidence": "official registry update; outcome direction is not inferred",
    }


def test_registry_results_are_official_registry_only_and_not_bullish_or_bearish():
    intelligence = build_catalyst_intelligence(
        [
            _registry_event(
                "ClinicalTrials.gov results posted — A Study of Example Therapy",
                "REGISTRY_RESULTS",
                10,
            )
        ],
        [{"symbol": "MRNA", "relative_volume": 2.0}],
    )
    cluster = intelligence["by_symbol"]["MRNA"]

    assert cluster["source_family"] == "clinicaltrials"
    assert cluster["verification_state"] == "OFFICIAL_REGISTRY_ONLY"
    assert cluster["category"] == "TRIAL_RESULTS_POSTED_REGISTRY"
    assert cluster["directional_bias"] == "mixed"
    assert cluster["official_confirmed"] is False
    assert cluster["official_registry"] is True
    assert cluster["explosion_impact"]["score_is_probability"] is False


def test_registry_status_update_does_not_become_failed_trial_claim():
    intelligence = build_catalyst_intelligence(
        [
            _registry_event(
                "ClinicalTrials.gov status TERMINATED — A Study of Example Therapy",
                "REGISTRY_STATUS",
                -8,
            )
        ],
        [{"symbol": "MRNA", "relative_volume": 1.2}],
    )
    cluster = intelligence["by_symbol"]["MRNA"]

    assert cluster["category"] == "TRIAL_STATUS_UPDATE_REGISTRY"
    assert cluster["directional_bias"] == "mixed"
    assert cluster["category"] != "TRIAL_FAILED"
