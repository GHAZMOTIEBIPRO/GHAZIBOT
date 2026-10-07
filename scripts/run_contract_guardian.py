from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from options_radar.contract_guardian import render_guardian_ar, update_contract_guardian


def _load(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value


def _save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Track BLACK BOX selected option contracts and frozen targets."
    )
    parser.add_argument("--payload", default="public/data/latest.json")
    parser.add_argument("--state", default="data/live/contract_guardian_state.json")
    parser.add_argument("--output", default="public/data/contract_guardian.json")
    parser.add_argument("--max-quote-age-minutes", type=float, default=120.0)
    args = parser.parse_args()

    payload_path = Path(args.payload)
    state_path = Path(args.state)
    output_path = Path(args.output)

    payload = _load(payload_path, {})
    if not isinstance(payload, dict):
        raise RuntimeError("guardian payload must be a JSON object")
    state = _load(state_path, {"contracts": {}})
    if not isinstance(state, dict):
        state = {"contracts": {}}

    report, updated_state = update_contract_guardian(
        payload,
        state,
        max_quote_age_minutes=max(1.0, args.max_quote_age_minutes),
    )
    report["report_ar"] = render_guardian_ar(report)

    payload["contract_guardian"] = report
    summary = payload.setdefault("summary", {})
    summary["guardian_tracked_contracts"] = report["tracked_total"]
    summary["guardian_active_contracts"] = report["active_count"]
    summary["guardian_terminal_contracts"] = report["terminal_count"]

    _save(state_path, updated_state)
    _save(output_path, report)
    _save(payload_path, payload)

    print(
        "Contract Guardian: "
        f"tracked={report['tracked_total']} "
        f"active={report['active_count']} "
        f"terminal={report['terminal_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
