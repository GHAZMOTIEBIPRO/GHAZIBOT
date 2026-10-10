from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yfinance as yf

from options_radar.research_attribution import (
    build_stock_research_features,
    evaluate_stock_research_attribution,
)


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _download_daily(symbol: str, period: str):
    return yf.download(
        symbol,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )


def enrich(
    audit_path: str | Path,
    *,
    period: str = "1y",
    max_workers: int = 6,
) -> dict[str, Any]:
    destination = Path(audit_path)
    audit = _read(destination)
    records = audit.get("records") if isinstance(audit.get("records"), dict) else {}
    symbols = sorted(
        {
            str(row.get("symbol") or "").upper().strip()
            for row in records.values()
            if isinstance(row, dict)
            and row.get("audit_status") in {"success", "failed"}
            and str(row.get("symbol") or "").strip()
        }
    )

    histories: dict[str, Any] = {}
    errors: dict[str, str] = {}
    workers = max(1, min(int(max_workers), 8, len(symbols) or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_download_daily, symbol, period): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                history = future.result()
                if history is None or history.empty:
                    errors[symbol] = "empty daily history"
                else:
                    histories[symbol] = history
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}: {exc}"

    enriched = 0
    for row in records.values():
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        history = histories.get(symbol)
        if history is None:
            continue
        try:
            row["research_features"] = build_stock_research_features(row, history)
            enriched += 1
        except Exception as exc:
            row["research_feature_error"] = f"{type(exc).__name__}: {exc}"

    audit["open_source_feature_attribution"] = evaluate_stock_research_attribution(audit)
    audit["research_feature_enrichment"] = {
        "version": "OPEN_SOURCE_ATTRIBUTION_V1",
        "period": period,
        "symbols_requested": len(symbols),
        "symbols_loaded": len(histories),
        "records_enriched": enriched,
        "errors": errors,
        "decision_authority": False,
        "live_alert_weights_changed": False,
    }
    _write(destination, audit)
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Attach causal SMC/chart/SEC research features to audited stock outcomes."
    )
    parser.add_argument("--audit", default="data/live/stock_outcome_audit.json")
    parser.add_argument("--period", default="1y")
    parser.add_argument("--max-workers", type=int, default=6)
    args = parser.parse_args()
    audit = enrich(
        args.audit,
        period=args.period,
        max_workers=args.max_workers,
    )
    report = audit.get("open_source_feature_attribution") or {}
    print(
        "Open-source stock attribution: "
        f"eligible={int(report.get('eligible_records', 0) or 0)} "
        f"enriched={int((audit.get('research_feature_enrichment') or {}).get('records_enriched', 0) or 0)} "
        f"authority={bool(report.get('decision_authority'))}"
    )


if __name__ == "__main__":
    main()
