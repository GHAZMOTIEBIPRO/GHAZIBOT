from datetime import datetime, timedelta, timezone

from scripts.prune_actions_artifacts import ArtifactRecord, select_artifacts_for_deletion


def _artifact(artifact_id: int, name: str, hours_old: float, size: int) -> ArtifactRecord:
    now = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
    return ArtifactRecord(
        artifact_id=artifact_id,
        name=name,
        size_in_bytes=size,
        created_at=now - timedelta(hours=hours_old),
    )


def test_keeps_newest_copies_per_name_and_age_floor():
    now = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
    artifacts = [
        _artifact(1, "state", 1, 10),
        _artifact(2, "state", 2, 20),
        _artifact(3, "state", 3, 30),
        _artifact(4, "state", 4, 40),
        _artifact(5, "state", 12, 50),
    ]
    selected = select_artifacts_for_deletion(
        artifacts,
        now=now,
        keep_per_name=2,
        min_age_hours=6,
        max_deletions=20,
    )
    assert [item.artifact_id for item in selected] == [5]


def test_prunes_each_name_independently_and_largest_first():
    now = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
    artifacts = [
        _artifact(1, "a", 1, 1),
        _artifact(2, "a", 10, 100),
        _artifact(3, "b", 1, 1),
        _artifact(4, "b", 10, 500),
    ]
    selected = select_artifacts_for_deletion(
        artifacts,
        now=now,
        keep_per_name=1,
        min_age_hours=2,
        max_deletions=20,
    )
    assert [item.artifact_id for item in selected] == [4, 2]


def test_deletion_cap_is_respected():
    now = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)
    artifacts = [_artifact(index, "state", index + 1, index * 10) for index in range(1, 12)]
    selected = select_artifacts_for_deletion(
        artifacts,
        now=now,
        keep_per_name=1,
        min_age_hours=1,
        max_deletions=3,
    )
    assert len(selected) == 3
