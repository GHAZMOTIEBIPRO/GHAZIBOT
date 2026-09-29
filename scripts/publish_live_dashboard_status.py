from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_state_vault import validate_runtime_file
except ModuleNotFoundError:  # Direct GitHub Actions script invocation.
    from runtime_state_vault import validate_runtime_file


PATH_SPECS: dict[str, dict[str, Any]] = {
    "fast_discovery": {
        "file": "data/live/fast_explosion_scan.json",
        "maximum_age_minutes": 45.0,
        "collections": ("stocks", "candidates", "signals"),
    },
    "stocks": {
        "file": "public/data/stocks_latest.json",
        "maximum_age_minutes": 90.0,
        "collections": ("stocks",),
    },
    "options": {
        "file": "public/data/options_latest.json",
        "maximum_age_minutes": 45.0,
        "collections": (
            "production_directional_signals",
            "free_directional_signals",
            "directional_signals",
            "contracts",
        ),
    },
}


def _now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _non_empty_count(payload: dict[str, Any], candidates: tuple[str, ...]) -> int:
    for key in candidates:
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _unavailable_path_status(name: str) -> dict[str, Any]:
    spec = PATH_SPECS[name]
    relative = str(spec["file"])
    return {
        "status": "UNAVAILABLE",
        "file": relative,
        "maximum_age_minutes": spec["maximum_age_minutes"],
        "reasons": ["No validated payload has been published for this path."],
    }


def _path_status_from_payload(
    name: str, payload: dict[str, Any], current: datetime
) -> dict[str, Any]:
    spec = PATH_SPECS[name]
    relative = str(spec["file"])

    generated_at = str(payload.get("generated_at") or "")
    generated = _parse_timestamp(generated_at)
    maximum_age = float(spec["maximum_age_minutes"])
    if generated is None:
        return {
            "status": "CRITICAL",
            "file": relative,
            "generated_at": generated_at or None,
            "maximum_age_minutes": maximum_age,
            "reasons": ["Payload has no valid generated_at timestamp."],
        }

    age_minutes = max(0.0, (current - generated).total_seconds() / 60.0)
    health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
    health_status = str(health.get("status") or "").upper()
    reasons = [str(item) for item in health.get("reasons", []) if str(item).strip()]
    status = "HEALTHY"
    if age_minutes > maximum_age:
        status = "STALE"
        reasons.insert(
            0,
            f"Payload age {age_minutes:.1f}m exceeds the {maximum_age:.0f}m safety limit.",
        )
    elif health_status in {"CRITICAL", "FAILED"}:
        status = "CRITICAL"
    elif health_status in {"DEGRADED", "WARNING"}:
        status = "DEGRADED"

    readiness = payload.get("provider_readiness")
    if name == "options" and isinstance(readiness, dict):
        readiness_status = str(readiness.get("status") or "UNKNOWN")
        if readiness.get("production_quote_ready") is not True:
            if status == "HEALTHY":
                status = "RESEARCH_ONLY"
            reasons.extend(
                str(item) for item in readiness.get("reasons", []) if str(item).strip()
            )
        else:
            readiness_status = "PRODUCTION_QUOTE_READY"
    else:
        readiness_status = None

    return {
        "status": status,
        "file": relative,
        "generated_at": generated.isoformat(),
        "age_minutes": round(age_minutes, 2),
        "maximum_age_minutes": maximum_age,
        "candidate_count": _non_empty_count(payload, tuple(spec["collections"])),
        "provider_readiness": readiness_status,
        "reasons": list(dict.fromkeys(reasons))[:8],
    }


def _path_status(name: str, root: Path, current: datetime) -> dict[str, Any]:
    payload = _load_json(root / str(PATH_SPECS[name]["file"]))
    if payload is None:
        return _unavailable_path_status(name)
    return _path_status_from_payload(name, payload, current)


def build_live_dashboard_status(
    *,
    state_root: Path,
    source_workflow: str,
    source_run_id: str,
    current: datetime,
    source_path: str | None = None,
    source_payload: Path | None = None,
) -> dict[str, Any]:
    previous = _load_json(state_root / "public/data/live_dashboard_status.json") or {}
    previous_paths = previous.get("paths") if isinstance(previous.get("paths"), dict) else {}
    paths: dict[str, dict[str, Any]] = {}
    for name in PATH_SPECS:
        prior = previous_paths.get(name)
        paths[name] = prior if isinstance(prior, dict) else _path_status(name, state_root, current)

    if (source_path is None) != (source_payload is None):
        raise ValueError("source_path and source_payload must be provided together")
    if source_path is not None and source_payload is not None:
        payload = _load_json(source_payload)
        if payload is None:
            raise ValueError(f"source payload is not a JSON object: {source_payload}")
        paths[source_path] = _path_status_from_payload(source_path, payload, current)

    critical = [
        name
        for name in ("fast_discovery", "stocks")
        if paths[name]["status"] in {"CRITICAL", "STALE", "UNAVAILABLE"}
    ]
    degraded = [
        name
        for name, path in paths.items()
        if path["status"] in {"DEGRADED", "RESEARCH_ONLY"}
        or (name == "options" and path["status"] == "UNAVAILABLE")
    ]
    if critical:
        overall = "CRITICAL"
    elif degraded:
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"

    reasons: list[str] = []
    for name, path in paths.items():
        if path["status"] != "HEALTHY":
            detail = "; ".join(path.get("reasons") or []) or path["status"]
            reasons.append(f"{name}: {detail}")

    return {
        "schema_version": 1,
        "decision_authority": False,
        "contains_secrets": False,
        "generated_at": current.isoformat(),
        "overall_status": overall,
        "paths": paths,
        "reasons": reasons[:16],
        "publisher": {
            "source_workflow": source_workflow,
            "source_run_id": str(source_run_id),
            "mode": "artifact_to_bot_state_status_only",
        },
    }


def publish_live_dashboard_status(
    *,
    state_root: Path,
    source_workflow: str,
    source_run_id: str,
    current: datetime,
    source_path: str | None = None,
    source_payload: Path | None = None,
) -> Path:
    output = state_root / "public/data/live_dashboard_status.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_live_dashboard_status(
        state_root=state_root,
        source_workflow=source_workflow,
        source_run_id=source_run_id,
        current=current,
        source_path=source_path,
        source_payload=source_payload,
    )
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validate_runtime_file(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Publish a non-decision dashboard status from validated radar artifacts."
    )
    parser.add_argument("--state-root", default=".bot-state/runtime")
    parser.add_argument("--source-workflow", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--source-path", choices=sorted(PATH_SPECS))
    parser.add_argument("--source-payload")
    parser.add_argument("--now", help="ISO-8601 UTC time for deterministic validation")
    args = parser.parse_args()
    if bool(args.source_path) != bool(args.source_payload):
        parser.error("--source-path and --source-payload must be provided together")

    output = publish_live_dashboard_status(
        state_root=Path(args.state_root),
        source_workflow=args.source_workflow,
        source_run_id=args.source_run_id,
        current=_now(args.now),
        source_path=args.source_path,
        source_payload=Path(args.source_payload) if args.source_payload else None,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
