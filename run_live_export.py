from __future__ import annotations

import json
import os
from pathlib import Path

# The public page should always show a ranked watchlist. Strong alert thresholds
# remain unchanged; only display-level option filtering is relaxed for free data.
os.environ.setdefault("MIN_SCORE", "50")
os.environ.setdefault("MIN_OPTION_VOLUME", "25")
os.environ.setdefault("MAX_SPREAD_PCT", "0.25")

import options_radar.catalysts as catalyst_module
import options_radar.stocks as stock_module
from options_radar.calibration_report import write_calibration_markdown
from options_radar.live_scanners import PublicStockRadar
from options_radar.operations import build_operational_status
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
