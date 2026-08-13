from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from options_radar.catalysts import CatalystScanner
from options_radar.official_catalyst_intelligence import build_catalyst_intelligence
from options_radar.settings import Settings

DEFAULT_FAST = Path("data/live/fast_explosion_scan.json")
DEFAULT_OUTPUT = Path("public/data/stocks_latest.json")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _load(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    output: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        row: dict[str, Any] = {}
        for key, value in raw.items():
            try:
                if pd.isna(value):
                    value = None
            except (TypeError, ValueError):
                pass
            if isinstance(value, pd.Timestamp):
                value = value.isoformat()
            elif hasattr(value, "item"):
                try:
                    value = value.item()
                except (TypeError, ValueError):
                    pass
            row[str(key)] = value
        output.append(row)
    return output


def _halt_map(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        if symbol:
            output.setdefault(symbol, []).append(row)
    return output


def _halt_semantics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        reason = str(row.get("reason") or "HALT").upper()
        if reason == "T1":
            role = "INFORMATION_EVENT"
            note = "News Pending: يوجد حدث معلوماتي ينتظر النشر؛ ليس اتجاهًا سعريًا بحد ذاته"
        elif reason == "T2":
            role = "INFORMATION_EVENT"
            note = "News Released: الخبر نُشر والسوق ينتظر الاستئناف؛ يجب مطابقة الخبر بالمصدر الأولي"
        elif reason in {"LUDP", "T5"}:
            role = "PRICE_CONFIRMATION"
            note = "إيقاف بسبب حركة سعرية/تذبذب؛ تأكيد شدة الحركة وليس سببها الأساسي"
        else:
            role = "MARKET_STATUS"
            note = "حالة تشغيل سوق تحتاج تفسيرًا حسب كود الإيقاف"
        row["evidence_role"] = role
        row["note_ar"] = note
        output.append(row)
    return output


def _amplifiers(row: dict[str, Any]) -> list[str]:
    output: list[str] = []
    supply = _number(row.get("supply_score"))
    turnover = _number(row.get("turnover_pct"))
    volume = _number(row.get("volume"))
    move = _number(row.get("move_pct"))
    if supply >= 70:
        output.append(f"ضغط/قلة معروض {supply:.0f}/100")
    if turnover >= 0.5:
        output.append(f"دوران سيولة إلى القيمة السوقية {turnover:.2f}%")
    if volume > 0:
        output.append(f"حجم تداول {volume:,.0f}")
    if abs(move) >= 2:
        output.append(f"حركة سعرية حالية {move:+.1f}%")
    return output


def run(
    *,
    fast_path: str | Path = DEFAULT_FAST,
    output_path: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    fast = _load(fast_path)
    actionable = [
        dict(row)
        for row in fast.get("actionable", [])
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    ]
    symbols = list(dict.fromkeys(str(row["symbol"]).upper() for row in actionable))
    halts = [dict(row) for row in fast.get("halts", []) if isinstance(row, dict)]
    halts_by_symbol = _halt_map(halts)

    settings = Settings()
    settings.validate()
    catalyst_errors: list[str] = []
    try:
        catalyst_frame = CatalystScanner(settings).scan(symbols, lookback_days=7)
    except Exception as exc:
        catalyst_frame = pd.DataFrame()
        catalyst_errors.append(f"{type(exc).__name__}: {exc}")
    catalyst_rows = _records(catalyst_frame)
    intelligence = build_catalyst_intelligence(catalyst_rows, actionable)
    cause_by_symbol = intelligence.get("by_symbol") if isinstance(intelligence.get("by_symbol"), dict) else {}

    stocks: list[dict[str, Any]] = []
    for raw in actionable:
        symbol = str(raw.get("symbol") or "").upper()
        cause = cause_by_symbol.get(symbol) if isinstance(cause_by_symbol.get(symbol), dict) else {}
        cause_eligible = bool(cause.get("primary_cause_eligible"))
        official = bool(cause.get("official_confirmed"))
        if cause_eligible:
            cause_block = {
                "status": "OFFICIAL_CONFIRMED" if official else str(cause.get("verification_state") or "PRIMARY_UNCONFIRMED"),
                "status_ar": cause.get("cause_status_ar") or ("سبب مؤكد رسميًا" if official else "سبب أولي يحتاج تأكيدًا"),
                "category": cause.get("category") or cause.get("category_normalized"),
                "headline": cause.get("headline"),
                "source": cause.get("primary_source"),
                "source_tier": cause.get("source_tier"),
                "url": cause.get("primary_url"),
                "official_confirmed": official,
            }
        else:
            cause_block = {
                "status": "NO_PRIMARY_CAUSE_PROVEN",
                "status_ar": "السبب الأساسي غير مثبت حتى الآن",
                "category": None,
                "headline": None,
                "source": None,
                "source_tier": None,
                "url": None,
                "official_confirmed": False,
            }

        current_halts = _halt_semantics(halts_by_symbol.get(symbol, []))
        stocks.append(
            {
                **raw,
                "cause": cause_block,
                "amplifiers": _amplifiers(raw),
                "market_status_evidence": current_halts,
                "independent_from_options_radar": True,
                "options_required_for_stock_signal": False,
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "path": "stocks",
        "architecture": "independent_stock_radar_v1",
        "independent_from_options_radar": True,
        "source_fast_scan_generated_at": fast.get("generated_at"),
        "summary": {
            "market_rows_seen": int(_number(fast.get("market_rows_seen"))),
            "fast_actionable": len(actionable),
            "stocks_deep_validated": len(stocks),
            "official_causes": sum(bool((row.get("cause") or {}).get("official_confirmed")) for row in stocks),
            "halt_events_seen": len(halts),
            "news_events_seen_fast": int(_number(fast.get("news_events_seen"))),
        },
        "policy": {
            "official_first": True,
            "halt_is_not_automatically_cause": True,
            "ludp_is_price_confirmation_not_primary_cause": True,
            "finviz_reddit_x_are_attention_not_proof": True,
            "options_flow_required": False,
        },
        "stocks": stocks,
        "catalyst_intelligence": intelligence,
        "catalysts": catalyst_rows,
        "halts": _halt_semantics(halts),
        "errors": catalyst_errors,
        "limitations": [
            "Fast price/volume discovery and deep catalyst validation are separate stages inside the stock path.",
            "A price move can remain actionable while its primary cause is unknown; the bot must say so explicitly.",
            "Options data never gates or creates a stock-path signal.",
        ],
    }

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(destination)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build independent stock-only BLACK BOX radar payload")
    parser.add_argument("--fast", default=str(DEFAULT_FAST))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    payload = run(fast_path=args.fast, output_path=args.output)
    print(
        "Independent stock radar: "
        f"market={payload['summary']['market_rows_seen']} "
        f"actionable={payload['summary']['fast_actionable']} "
        f"official_causes={payload['summary']['official_causes']}"
    )


if __name__ == "__main__":
    main()
