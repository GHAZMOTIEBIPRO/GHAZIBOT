from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from options_radar.adaptive_learning import build_learning_model, save_learning_model
from options_radar.calibration import build_calibration_report
from options_radar.durable_stock_state import restore_missing_durable_stock_state
from options_radar.free_autonomy import enforce_free_autonomy_environment
from options_radar.outcomes import SignalJournal
from options_radar.settings import Settings
from options_radar.stock_outcome_archive import update_stock_outcome_archive

DEFAULT_OUTPUT = Path("data/live/adaptive_learning.json")
DEFAULT_REPORT = Path("data/live/adaptive_learning_report.json")
DEFAULT_STOCK_OUTCOMES = Path("data/live/stock_outcomes.json")
DEFAULT_STOCK_ARCHIVE = Path(
    os.getenv("STOCK_OUTCOME_ARCHIVE_PATH", "data/live/stock_outcome_archive.json")
)
DEFAULT_STOCK_AUDIT = Path(
    os.getenv("STOCK_OUTCOME_AUDIT_PATH", "data/live/stock_outcome_audit.json")
)


def _read(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run(
    *,
    output_path: str | Path = DEFAULT_OUTPUT,
    report_path: str | Path = DEFAULT_REPORT,
    stock_outcomes_path: str | Path = DEFAULT_STOCK_OUTCOMES,
    stock_archive_path: str | Path = DEFAULT_STOCK_ARCHIVE,
    stock_audit_path: str | Path = DEFAULT_STOCK_AUDIT,
    refresh_options: bool = True,
) -> dict[str, Any]:
    free_status = enforce_free_autonomy_environment()
    durable = restore_missing_durable_stock_state()

    archive = update_stock_outcome_archive(
        stock_outcomes_path,
        stock_archive_path,
        now=datetime.now(timezone.utc),
    )
    stock_audit = _read(stock_audit_path)

    settings = Settings()
    settings.validate()
    option_outcome_summary: dict[str, Any] = {}
    errors: list[str] = []

    if refresh_options:
        try:
            journal = SignalJournal(
                settings.signal_journal_path,
                settings.outcome_path,
                settings.model_version,
                settings=settings,
            )
            option_outcome_summary = journal.update_outcomes(datetime.now(timezone.utc))
        except Exception as exc:
            errors.append(f"options_outcome_refresh: {type(exc).__name__}: {exc}")

    model = build_learning_model(
        stock_outcomes_path=stock_outcomes_path,
        stock_archive_path=stock_archive_path,
        options_signals_path=settings.signal_journal_path,
        options_outcomes_path=settings.outcome_path,
    )
    save_learning_model(output_path, model)

    calibration = build_calibration_report(
        signals_path=settings.signal_journal_path,
        outcomes_path=settings.outcome_path,
        minimum_sample=settings.calibration_minimum_sample,
    )
    stock_model_sample_ready = bool((model.get("stock") or {}).get("ready"))
    audit_gate = stock_audit.get("promotion_gate") if isinstance(stock_audit.get("promotion_gate"), dict) else {}
    audit_coverage = stock_audit.get("coverage") if isinstance(stock_audit.get("coverage"), dict) else {}
    stock_audit_coverage_ready = audit_gate.get("coverage_ready") is True
    stock_ready_for_walk_forward = stock_model_sample_ready and stock_audit_coverage_ready

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "SHADOW_LEARNING",
        "live_alert_weights_changed": False,
        "free_autonomy": {
            "enabled": free_status.enabled,
            "stock_feed": free_status.stock_stream_feed,
            "option_feed": free_status.option_stream_feed,
            "paid_market_data_allowed": free_status.paid_market_data_allowed,
        },
        "durable_stock_state": {
            "attempted": durable.attempted,
            "branch_available": durable.branch_available,
            "restored": list(durable.restored),
            "preserved_local": list(durable.preserved_local),
            "error": durable.error,
        },
        "stock_archive_summary": archive.get("summary", {}),
        "stock_outcome_audit": {
            "available": bool(stock_audit),
            "coverage_60m_pct": float(audit_coverage.get("coverage_60m_pct", 0.0) or 0.0),
            "independent_60m_sessions": int(audit_coverage.get("independent_60m_sessions", 0) or 0),
            "decisive": int(audit_coverage.get("decisive", 0) or 0),
            "ambiguous": int(audit_coverage.get("ambiguous", 0) or 0),
            "non_decisive": int(audit_coverage.get("non_decisive", 0) or 0),
            "coverage_ready": stock_audit_coverage_ready,
        },
        "option_outcome_summary": option_outcome_summary,
        "calibration": calibration,
        "model": model,
        "errors": errors,
        "promotion_gate": {
            # `stock_ready` is retained for backward compatibility but means only
            # the historical minimum sample exists; it is never a live-ready flag.
            "stock_ready": stock_model_sample_ready,
            "stock_model_sample_ready": stock_model_sample_ready,
            "stock_outcome_audit_coverage_ready": stock_audit_coverage_ready,
            "stock_ready_for_walk_forward": stock_ready_for_walk_forward,
            "stock_walk_forward_passed": False,
            "stock_ready_for_live_promotion": False,
            "options_ready": bool((model.get("options") or {}).get("ready")),
            "requires_outcome_audit_before_walk_forward": True,
            "requires_walk_forward_review_before_live_promotion": True,
        },
    }
    _write(Path(report_path), report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run isolated BLACK BOX adaptive learning cycle")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--stock-outcomes", default=str(DEFAULT_STOCK_OUTCOMES))
    parser.add_argument("--stock-archive", default=str(DEFAULT_STOCK_ARCHIVE))
    parser.add_argument("--stock-audit", default=str(DEFAULT_STOCK_AUDIT))
    parser.add_argument("--no-option-refresh", action="store_true")
    args = parser.parse_args()
    report = run(
        output_path=args.output,
        report_path=args.report,
        stock_outcomes_path=args.stock_outcomes,
        stock_archive_path=args.stock_archive,
        stock_audit_path=args.stock_audit,
        refresh_options=not args.no_option_refresh,
    )
    model = report.get("model", {})
    archive = report.get("stock_archive_summary", {})
    gate = report.get("promotion_gate", {})
    print(
        "Adaptive learning cycle: "
        f"stock_sample_ready={bool(gate.get('stock_model_sample_ready'))} "
        f"stock_audit_ready={bool(gate.get('stock_outcome_audit_coverage_ready'))} "
        f"stock_walk_forward_ready={bool(gate.get('stock_ready_for_walk_forward'))} "
        f"stock_archive={int(archive.get('records', 0) or 0)} "
        f"options_ready={bool((model.get('options') or {}).get('ready'))} "
        f"errors={len(report.get('errors', []))}"
    )


if __name__ == "__main__":
    main()
