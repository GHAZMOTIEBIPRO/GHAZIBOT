from types import SimpleNamespace

from scripts.fast_explosion_scan_fabric import _apply_validation_to_candidate


def _candidate():
    return SimpleNamespace(
        symbol="TEST",
        score=80.0,
        institutional_priority=80.0,
        reasons=[],
    )


def test_two_transports_from_one_family_do_not_upgrade_confidence():
    candidate = _candidate()
    _apply_validation_to_candidate(
        candidate,
        {
            "available": True,
            "fabric_transport_source_count": 2,
            "fabric_independent_source_count": 1,
            "fabric_consensus_pass": True,
            "nasdaq_vs_fabric_divergence_pct": 0.0,
        },
        regular=False,
        discovery_divergence=0.08,
    )

    assert candidate.institutional_priority == 80.0
    assert not any("عائلات مصادر مستقلة" in reason for reason in candidate.reasons)


def test_two_independent_families_can_upgrade_confidence():
    candidate = _candidate()
    _apply_validation_to_candidate(
        candidate,
        {
            "available": True,
            "fabric_transport_source_count": 2,
            "fabric_independent_source_count": 2,
            "fabric_consensus_pass": True,
            "nasdaq_vs_fabric_divergence_pct": 0.0,
        },
        regular=False,
        discovery_divergence=0.08,
    )

    assert candidate.institutional_priority == 82.0
    assert any("2 عائلات مصادر مستقلة" in reason for reason in candidate.reasons)


def test_transport_disagreement_can_still_reduce_confidence():
    candidate = _candidate()
    _apply_validation_to_candidate(
        candidate,
        {
            "available": True,
            "fabric_transport_source_count": 2,
            "fabric_independent_source_count": 1,
            "fabric_consensus_pass": False,
            "nasdaq_vs_fabric_divergence_pct": 0.0,
        },
        regular=False,
        discovery_divergence=0.08,
    )

    assert candidate.institutional_priority == 70.0
    assert any("اختلاف واضح" in reason for reason in candidate.reasons)
