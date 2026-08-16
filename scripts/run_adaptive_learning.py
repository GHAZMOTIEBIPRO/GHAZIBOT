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
    refresh_options: bool = True,
) -> dict[str, Any]:
    free_status = enforce_free_autonomy_environment()
    durable = restore_missing_durable_stock_state()

    archive = update_stock_outcome_archive(
        stock_outcomes_path,
        stock_archive_path,
        now=datetime.now(timezone.utc),
    )

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
        "option_outcome_summary": option_outcome_summary,
        "calibration": calibration,
        "model": model,
        "errors": errors,
        "promotion_gate": {
            "stock_ready": bool((model.get("stock") or {}).get("ready")),
            "options_ready": bool((model.get("options") or {}).get("ready")),
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
    parser.add_argument("--no-option-refresh", action="store_true")
    args = parser.parse_args()
    report = run(
        output_path=args.output,
        report_path=args.report,
        stock_outcomes_path=args.stock_outcomes,
        stock_archive_path=args.stock_archive,
        refresh_options=not args.no_option_refresh,
    )
    model = report.get("model", {})
    archive = report.get("stock_archive_summary", {})
    print(
        "Adaptive learning cycle: "
        f"stock_ready={bool((model.get('stock') or {}).get('ready'))} "
        f"stock_archive={int(archive.get('records', 0) or 0)} "
        f"options_ready={bool((model.get('options') or {}).get('ready'))} "
        f"errors={len(report.get('errors', []))}"
    )


if __name__ == "__main__":
    main()
