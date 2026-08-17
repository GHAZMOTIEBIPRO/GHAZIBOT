from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

# These files were historically committed to main after each research scan.
# They are public research/runtime state, not credentials. Keep the allowlist
# explicit so bot-state cannot accidentally become a dump of the repository.
RUNTIME_PATHS = (
    "public/data/latest.json",
    "public/data/health.json",
    "public/data/data-status.json",
    "data/cache/sec_efts_events.json",
    "data/cache/sec_efts_status.json",
    "data/cache/sec_processed_accessions.json",
    "data/cache/sec_incremental_status.json",
    "data/live/source_audit.json",
    "data/live/intelligence_audit.json",
    "data/live/occ_audit.json",
    "data/live/spx_0dte_snapshot.json",
    "data/live/alert_state.json",
    "data/live/signals.jsonl",
    "data/live/outcomes.json",
    "data/live/calibration.json",
    "data/live/CALIBRATION_REVIEW.md",
    "data/live/calibration_issue.json",
)

SECRET_KEY_TOKENS = (
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "password",
    "credential",
)


def _has_secret_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(token in normalized for token in SECRET_KEY_TOKENS):
                return True
            if _has_secret_key(child):
                return True
        return False
    if isinstance(value, list):
        return any(_has_secret_key(item) for item in value)
    return False


def _validate_json(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if _has_secret_key(payload):
        raise ValueError(f"secret-like key rejected from runtime vault: {path}")


def _validate_jsonl(path: Path) -> None:
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if _has_secret_key(payload):
            raise ValueError(f"secret-like key rejected from runtime vault: {path}:{index}")


def validate_runtime_file(path: Path) -> None:
    if path.suffix == ".json":
        _validate_json(path)
    elif path.suffix == ".jsonl":
        _validate_jsonl(path)


def restore_runtime_state(*, repo_root: Path, vault_root: Path) -> dict[str, int]:
    restored = 0
    missing = 0
    for relative in RUNTIME_PATHS:
        source = vault_root / relative
        destination = repo_root / relative
        if not source.exists():
            missing += 1
            continue
        validate_runtime_file(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        restored += 1
    return {"restored": restored, "missing": missing}


def publish_runtime_state(*, repo_root: Path, vault_root: Path) -> dict[str, int]:
    published = 0
    missing = 0
    for relative in RUNTIME_PATHS:
        source = repo_root / relative
        destination = vault_root / relative
        if not source.exists():
            missing += 1
            continue
        validate_runtime_file(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        published += 1

    manifest = {
        "schema_version": 1,
        "decision_authority": False,
        "contains_secrets": False,
        "source": "GHAZI Stocks and Options Radar",
        "published_files": published,
        "allowlist": list(RUNTIME_PATHS),
    }
    manifest_path = vault_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"published": published, "missing": missing}


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore/publish public runtime research state via bot-state.")
    parser.add_argument("mode", choices=("restore", "publish"))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--vault-root", default=".bot-state/runtime")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    vault_root = Path(args.vault_root).resolve()
    if args.mode == "restore":
        result = restore_runtime_state(repo_root=repo_root, vault_root=vault_root)
    else:
        result = publish_runtime_state(repo_root=repo_root, vault_root=vault_root)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
