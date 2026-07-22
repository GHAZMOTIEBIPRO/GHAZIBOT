from __future__ import annotations

from pathlib import Path
from typing import Any


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _number(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def render_calibration_markdown(report: dict[str, Any], model_version: str) -> str:
    ready = bool(report.get("calibration_ready"))
    priced = int(report.get("priced_sample", 0) or 0)
    minimum = int(report.get("minimum_sample", 100) or 100)
    status = "READY FOR INDEPENDENT REVIEW" if ready else "COLLECTING EVIDENCE"

    lines = [
        "# GHAZI Radar — Calibration Review",
        "",
        f"- **Model version:** `{model_version}`",
        f"- **Status:** **{status}**",
        f"- **Priced signals:** **{priced}/{minimum}**",
        f"- **Decision:** {report.get('decision', '—')}",
        "",
        "> This report does not authorize automatic score changes. It opens a review gate only. ",
        "> Free-data observations are not proof of executable fills or the order in which targets and stops were reached.",
        "",
        "## Score bands",
        "",
        "| Band | Signals | Priced | Target 1 | Target 2 | Stop | Avg MFE % | Avg MAE % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.get("score_bands", []):
        lines.append(
            "| {band} | {signals} | {priced} | {t1} | {t2} | {stop} | {mfe} | {mae} |".format(
                band=row.get("band", "—"),
                signals=int(row.get("signals", 0) or 0),
                priced=int(row.get("priced", 0) or 0),
                t1=_pct(row.get("target_1_rate")),
                t2=_pct(row.get("target_2_rate")),
                stop=_pct(row.get("stop_rate")),
                mfe=_number(row.get("average_mfe_pct")),
                mae=_number(row.get("average_mae_pct")),
            )
        )

    lines.extend([
        "",
        "## Catalyst groups",
        "",
        "| Catalyst | Signals | Target 1 | Stop | Avg MFE % |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in report.get("catalysts", []):
        lines.append(
            "| {name} | {signals} | {t1} | {stop} | {mfe} |".format(
                name=str(row.get("catalyst", "—")).replace("|", "/"),
                signals=int(row.get("signals", 0) or 0),
                t1=_pct(row.get("target_1_rate")),
                stop=_pct(row.get("stop_rate")),
                mfe=_number(row.get("average_mfe_pct")),
            )
        )

    lines.extend([
        "",
        "## Review protocol",
        "",
        "When the gate becomes ready:",
        "",
        "1. Freeze the current model version and preserve its complete signal journal.",
        "2. Check whether higher score bands outperform lower bands after spread and slippage assumptions.",
        "3. Review results by catalyst, CALL/PUT side, DTE, Delta, market regime and data source.",
        "4. Reject weight changes that improve only the same sample used to propose them.",
        "5. Create a new model version and test it prospectively; never overwrite historical scores.",
        "6. Do not enable real-money automation solely because the minimum sample was reached.",
        "",
        f"_Generated from `{Path('data/live/calibration.json')}`._",
        "",
    ])
    return "\n".join(lines)


def write_calibration_markdown(
    report: dict[str, Any],
    model_version: str,
    path: str | Path = "data/live/CALIBRATION_REVIEW.md",
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        render_calibration_markdown(report, model_version), encoding="utf-8"
    )
    temporary.replace(destination)
    return destination
