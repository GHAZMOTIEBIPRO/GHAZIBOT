from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from options_radar.stock_walk_forward import run_stock_walk_forward


def _read(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(destination)


def run(*, audit_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    audit = _read(audit_path)
    report = run_stock_walk_forward(audit)
    _write(output_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fail-closed stock expanding-session walk-forward research.")
    parser.add_argument("--audit", default="data/live/stock_outcome_audit.json")
    parser.add_argument("--output", default="data/live/stock_walk_forward.json")
    args = parser.parse_args()
    report = run(audit_path=args.audit, output_path=args.output)
    gate = report.get("gate") if isinstance(report.get("gate"), dict) else {}
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    print(
        "Stock walk-forward: "
        f"status={report.get('status')} "
        f"coverage_60m={float(gate.get('coverage_60m_pct', 0.0) or 0.0):.2f}% "
        f"independent_sessions={int(gate.get('independent_60m_sessions', 0) or 0)} "
        f"oos_sessions={int(metrics.get('oos_sessions', 0) or 0)} "
        f"oos_records={int(metrics.get('oos_records', 0) or 0)} "
        f"research_passed={bool(report.get('research_passed'))} "
        f"live_promotion_allowed={bool(report.get('live_promotion_allowed'))}"
    )


if __name__ == "__main__":
    main()
