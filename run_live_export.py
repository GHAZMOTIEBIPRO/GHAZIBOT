from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

# The public page should always show a ranked watchlist. Strong alert thresholds
# remain unchanged; only display-level option filtering is relaxed for free data.
os.environ.setdefault("MIN_SCORE", "50")
os.environ.setdefault("MIN_OPTION_VOLUME", "25")
os.environ.setdefault("MAX_SPREAD_PCT", "0.25")

import options_radar.catalysts as catalyst_module
import options_radar.stocks as stock_module
from options_radar.calibration_report import write_calibration_markdown
from options_radar.live_scanners import PublicStockRadar
from options_radar.macro import build_macro_context
from options_radar.operations import build_operational_status
from options_radar.sec_fundamentals import enrich_stock_fundamentals
from options_radar.settings import Settings
from options_radar.strict_catalysts import StrictCatalystScanner

catalyst_module.CatalystScanner = StrictCatalystScanner
stock_module.StockRadar = PublicStockRadar

from export_web import main as export_main


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _json_safe(value):
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _fundamental_reason(row: dict) -> str:
    parts: list[str] = []
    revenue_growth = row.get("revenue_growth")
    net_margin = row.get("net_margin")
    operating_growth = row.get("operating_cash_flow_growth")
    if isinstance(revenue_growth, (int, float)) and not pd.isna(revenue_growth):
        parts.append(f"نمو الإيرادات SEC {revenue_growth * 100:+.1f}%")
    if isinstance(net_margin, (int, float)) and not pd.isna(net_margin):
        parts.append(f"هامش صافي SEC {net_margin * 100:.1f}%")
    if isinstance(operating_growth, (int, float)) and not pd.isna(operating_growth):
        parts.append(f"نمو التدفق التشغيلي SEC {operating_growth * 100:+.1f}%")
    return "؛ ".join(parts)


def _enrich_stocks(payload: dict, settings: Settings) -> dict[str, str]:
    records = payload.get("stocks", [])
    if not isinstance(records, list) or not records:
        return {}
    frame = pd.DataFrame(records)
    enriched, errors = enrich_stock_fundamentals(frame, settings, max_symbols=8)
    output_records = []
    for row in enriched.to_dict(orient="records"):
        safe = {str(key): _json_safe(value) for key, value in row.items()}
        summary = _fundamental_reason(safe)
        if summary:
            existing = str(safe.get("reasons") or "")
            safe["reasons"] = f"{existing}؛ {summary}" if existing else summary
        output_records.append(safe)
    payload["stocks"] = output_records
    return errors


def _has_level(row: dict, key: str) -> bool:
    value = row.get(key)
    return isinstance(value, (int, float)) and not pd.isna(value)


def _correct_path_metrics(payload: dict, settings: Settings) -> None:
    """Exclude pre-phase3 records that never stored underlying targets/stops."""

    if not settings.outcome_path.exists():
        return
    try:
        outcomes = json.loads(settings.outcome_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    states = outcomes.get("signals", {})
    if not isinstance(states, dict):
        return

    meaningful: list[dict] = []
    changed = False
    for state in states.values():
        if not isinstance(state, dict):
            continue
        has_levels = _has_level(state, "underlying_target_1") and _has_level(
            state, "underlying_invalidation"
        )
        if state.get("path_status") == "evaluated" and not has_levels:
            state["path_status"] = "missing_levels"
            state["outcome_order"] = "not_evaluable"
            changed = True
        if state.get("path_status") == "evaluated" and has_levels:
            meaningful.append(state)

    performance = payload.setdefault("performance", {})
    performance["path_evaluated"] = len(meaningful)
    performance["path_target_1_first"] = sum(
        row.get("outcome_order") == "target_1_first" for row in meaningful
    )
    performance["path_target_2_first"] = sum(
        row.get("outcome_order") == "target_2_first" for row in meaningful
    )
    performance["path_stop_first"] = sum(
        row.get("outcome_order") == "stop_first" for row in meaningful
    )
    performance["path_ambiguous"] = sum(
        row.get("outcome_order") == "ambiguous_same_bar" for row in meaningful
    )
    performance["legacy_paths_excluded"] = sum(
        isinstance(row, dict) and row.get("path_status") == "missing_levels"
        for row in states.values()
    )
    if changed:
        _write_json_atomic(settings.outcome_path, outcomes)


def publish_operational_state() -> None:
    settings = Settings()
    output = Path("public/data/latest.json")
    calibration_path = settings.calibration_path

    payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    calibration = (
        json.loads(calibration_path.read_text(encoding="utf-8"))
        if calibration_path.exists()
        else payload.get("calibration", {})
    )
    errors = payload.setdefault("errors", {})
    fundamental_errors = _enrich_stocks(payload, settings)
    errors.update({f"fundamentals:{key}": value for key, value in fundamental_errors.items()})
    macro, macro_errors = build_macro_context(settings)
    payload["macro"] = macro
    errors.update({f"macro:{key}": value for key, value in macro_errors.items()})
    _correct_path_metrics(payload, settings)

    operational = build_operational_status(settings)
    matured = int(calibration.get("matured_sample", calibration.get("priced_sample", 0)) or 0)
    minimum = int(calibration.get("minimum_sample", 100) or 100)
    payload["operational_status"] = operational
    payload["calibration_gate"] = {
        "ready": bool(calibration.get("calibration_ready")),
        "priced_sample": matured,
        "matured_sample": matured,
        "raw_priced_sample": int(calibration.get("raw_priced_sample", matured) or 0),
        "five_day_sample": int(calibration.get("five_day_sample", 0) or 0),
        "maturity_checkpoint": str(calibration.get("maturity_checkpoint", "1d")),
        "minimum_sample": minimum,
        "remaining": max(0, minimum - matured),
        "review_report": "data/live/CALIBRATION_REVIEW.md",
        "automatic_weight_changes": False,
    }
    _write_json_atomic(output, payload)
    write_calibration_markdown(calibration, settings.model_version)


if __name__ == "__main__":
    exit_code = export_main()
    if exit_code == 0:
        publish_operational_state()
    raise SystemExit(exit_code)
