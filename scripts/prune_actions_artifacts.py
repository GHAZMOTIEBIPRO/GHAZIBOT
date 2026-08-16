from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

API_ROOT = "https://api.github.com"


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: int
    name: str
    size_in_bytes: int
    created_at: datetime
    expired: bool = False


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_artifact(row: dict[str, Any]) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=int(row["id"]),
        name=str(row.get("name") or "unnamed"),
        size_in_bytes=max(0, int(row.get("size_in_bytes") or 0)),
        created_at=_utc(str(row["created_at"])),
        expired=bool(row.get("expired", False)),
    )


def select_artifacts_for_deletion(
    artifacts: list[ArtifactRecord],
    *,
    now: datetime,
    keep_per_name: int = 3,
    min_age_hours: float = 6.0,
    max_deletions: int = 400,
) -> list[ArtifactRecord]:
    """Keep the newest N copies per artifact name and prune older duplicates.

    The age floor avoids racing workflows that are still consuming freshly
    generated artifacts. Candidates are ordered by size first so a bounded run
    frees the most storage with the fewest API calls.
    """
    keep = max(1, int(keep_per_name))
    limit = max(1, int(max_deletions))
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=max(1.0, min_age_hours))
    grouped: dict[str, list[ArtifactRecord]] = defaultdict(list)
    for artifact in artifacts:
        if not artifact.expired:
            grouped[artifact.name].append(artifact)

    candidates: list[ArtifactRecord] = []
    for rows in grouped.values():
        rows.sort(key=lambda item: item.created_at, reverse=True)
        for artifact in rows[keep:]:
            if artifact.created_at <= cutoff:
                candidates.append(artifact)

    candidates.sort(
        key=lambda item: (item.size_in_bytes, -item.created_at.timestamp()),
        reverse=True,
    )
    return candidates[:limit]


class GitHubClient:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.token = token

    def _request(self, path: str, *, method: str = "GET") -> tuple[int, bytes]:
        request = urllib.request.Request(
            f"{API_ROOT}{path}",
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2026-03-10",
                "User-Agent": "GHAZIBOT-Actions-Housekeeping",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            raise RuntimeError(
                f"GitHub API {method} {path} failed: HTTP {exc.code} {body[:500]!r}"
            ) from exc

    def list_artifacts(self) -> list[ArtifactRecord]:
        output: list[ArtifactRecord] = []
        page = 1
        while True:
            _, body = self._request(
                f"/repos/{self.repository}/actions/artifacts?per_page=100&page={page}"
            )
            payload = json.loads(body.decode("utf-8"))
            rows = payload.get("artifacts") if isinstance(payload, dict) else []
            if not isinstance(rows, list) or not rows:
                break
            output.extend(parse_artifact(row) for row in rows if isinstance(row, dict))
            if len(rows) < 100:
                break
            page += 1
        return output

    def delete_artifact(self, artifact_id: int) -> None:
        status, _ = self._request(
            f"/repos/{self.repository}/actions/artifacts/{int(artifact_id)}",
            method="DELETE",
        )
        if status != 204:
            raise RuntimeError(f"Unexpected delete status: {status}")


def main() -> int:
    repository = str(os.getenv("GITHUB_REPOSITORY") or "").strip()
    token = str(os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or "").strip()
    if not repository or not token:
        print("GITHUB_REPOSITORY and GH_TOKEN/GITHUB_TOKEN are required.", file=sys.stderr)
        return 2

    keep_per_name = int(os.getenv("ACTIONS_ARTIFACT_KEEP_PER_NAME", "3"))
    min_age_hours = float(os.getenv("ACTIONS_ARTIFACT_MIN_AGE_HOURS", "6"))
    max_deletions = int(os.getenv("ACTIONS_ARTIFACT_MAX_DELETIONS", "400"))
    dry_run = str(os.getenv("ACTIONS_ARTIFACT_DRY_RUN", "false")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    client = GitHubClient(repository, token)
    artifacts = client.list_artifacts()
    candidates = select_artifacts_for_deletion(
        artifacts,
        now=datetime.now(timezone.utc),
        keep_per_name=keep_per_name,
        min_age_hours=min_age_hours,
        max_deletions=max_deletions,
    )
    total_bytes = sum(item.size_in_bytes for item in artifacts if not item.expired)
    reclaim_bytes = sum(item.size_in_bytes for item in candidates)
    print(
        f"Artifacts active={sum(not item.expired for item in artifacts)} "
        f"bytes={total_bytes} candidates={len(candidates)} reclaim_bytes={reclaim_bytes} "
        f"keep_per_name={keep_per_name} dry_run={dry_run}"
    )

    deleted = 0
    freed = 0
    if not dry_run:
        for artifact in candidates:
            client.delete_artifact(artifact.artifact_id)
            deleted += 1
            freed += artifact.size_in_bytes
            print(
                f"deleted id={artifact.artifact_id} name={artifact.name!r} "
                f"size={artifact.size_in_bytes} created={artifact.created_at.isoformat()}"
            )

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("# BLACK BOX Ω — Actions Storage Housekeeping\n\n")
            handle.write(f"- Active artifacts inspected: **{len(artifacts)}**\n")
            handle.write(f"- Deleted this run: **{deleted}**\n")
            handle.write(f"- Reclaimed bytes: **{freed:,}**\n")
            handle.write(f"- Newest copies kept per artifact name: **{keep_per_name}**\n")
            handle.write("- Trading/radar schedules changed by this job: **No**\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
