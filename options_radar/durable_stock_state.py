from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

STATE_BRANCH = "bot-state"
REMOTE_REF = f"refs/remotes/origin/{STATE_BRANCH}"
DURABLE_STOCK_FILES = (
    ("state/stocks/stock_outcomes.json", "data/live/stock_outcomes.json"),
    ("state/stocks/stock_outcome_archive.json", "data/live/stock_outcome_archive.json"),
    ("state/stocks/stock_outcome_audit.json", "data/live/stock_outcome_audit.json"),
    ("state/stocks/adaptive_learning.json", "data/live/adaptive_learning.json"),
)


@dataclass(frozen=True)
class DurableStockRestoreStatus:
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


def _valid_json(payload: bytes) -> bool:
    if not payload.strip():
        return False
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(value, dict)


def restore_missing_durable_stock_state(
    root: str | Path | None = None,
    *,
    branch: str = STATE_BRANCH,
) -> DurableStockRestoreStatus:
    """Fill missing stock research state without overwriting newer hot artifacts."""

    repository = Path(root or Path(__file__).resolve().parents[1]).resolve()
    missing: list[tuple[str, Path]] = []
    preserved: list[str] = []
    for remote_path, local_path in DURABLE_STOCK_FILES:
        destination = repository / local_path
        if destination.is_file() and destination.stat().st_size > 0:
            preserved.append(local_path)
        else:
            missing.append((remote_path, destination))

    if not missing:
        return DurableStockRestoreStatus(
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
        return DurableStockRestoreStatus(
            attempted=True,
            branch_available=False,
            restored=(),
            preserved_local=tuple(preserved),
            error=fetch.stderr.decode("utf-8", errors="replace").strip()[:400],
        )

    restored: list[str] = []
    for remote_path, destination in missing:
        show = _git(repository, "show", f"origin/{branch}:{remote_path}")
        if show.returncode != 0 or not _valid_json(show.stdout):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".durable.tmp")
        temporary.write_bytes(show.stdout)
        temporary.replace(destination)
        restored.append(str(destination.relative_to(repository)))

    return DurableStockRestoreStatus(
        attempted=True,
        branch_available=True,
        restored=tuple(restored),
        preserved_local=tuple(preserved),
    )
