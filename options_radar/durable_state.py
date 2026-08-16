from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

STATE_BRANCH = "bot-state"
REMOTE_REF = f"refs/remotes/origin/{STATE_BRANCH}"
DURABLE_FILES = (
    ("state/options/options_alert_state.json", "data/live/options_alert_state.json"),
    ("state/options/options_signals.jsonl", "data/live/options_signals.jsonl"),
    ("state/options/options_outcomes.json", "data/live/options_outcomes.json"),
    ("state/options/options_calibration.json", "data/live/options_calibration.json"),
)


@dataclass(frozen=True)
class DurableRestoreStatus:
    attempted: bool
    branch_available: bool
    restored: tuple[str, ...]
    preserved_local: tuple[str, ...]
    error: str = ""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=False,
        capture_output=True,
        timeout=30,
    )


def _valid_payload(path: str, payload: bytes) -> bool:
    if not payload.strip():
        return False
    if path.endswith(".json"):
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        return isinstance(value, dict)
    if path.endswith(".jsonl"):
        try:
            for line in payload.decode("utf-8").splitlines():
                if line.strip():
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        return False
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
    return True


def restore_missing_durable_options_state(
    root: str | Path | None = None,
    *,
    branch: str = STATE_BRANCH,
) -> DurableRestoreStatus:
    """Restore only missing option-learning files from the durable state branch.

    Recent workflow artifacts remain the preferred hot state. This fallback never
    overwrites a non-empty local file, so a slightly delayed state-vault commit
    cannot roll a newer run backward.
    """

    repository = Path(root or Path(__file__).resolve().parents[1]).resolve()
    missing: list[tuple[str, Path]] = []
    preserved: list[str] = []
    for remote_path, local_path in DURABLE_FILES:
        destination = repository / local_path
        if destination.is_file() and destination.stat().st_size > 0:
            preserved.append(local_path)
        else:
            missing.append((remote_path, destination))

    if not missing:
        return DurableRestoreStatus(
            attempted=False,
            branch_available=True,
            restored=(),
            preserved_local=tuple(preserved),
        )

    fetch = _git(
        repository,
        "fetch",
        "origin",
        f"{branch}:{REMOTE_REF}",
        "--depth=1",
        "--quiet",
    )
    if fetch.returncode != 0:
        error = fetch.stderr.decode("utf-8", errors="replace").strip()[:400]
        return DurableRestoreStatus(
            attempted=True,
            branch_available=False,
            restored=(),
            preserved_local=tuple(preserved),
            error=error,
        )

    restored: list[str] = []
    for remote_path, destination in missing:
        show = _git(repository, "show", f"origin/{branch}:{remote_path}")
        if show.returncode != 0 or not _valid_payload(remote_path, show.stdout):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".durable.tmp")
        temporary.write_bytes(show.stdout)
        temporary.replace(destination)
        restored.append(str(destination.relative_to(repository)))

    return DurableRestoreStatus(
        attempted=True,
        branch_available=True,
        restored=tuple(restored),
        preserved_local=tuple(preserved),
    )
