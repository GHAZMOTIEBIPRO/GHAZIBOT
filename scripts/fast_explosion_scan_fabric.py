from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.data_fabric_runtime import install_data_fabric
from options_radar.data_fabric_singleflight import install_data_fabric_singleflight
from options_radar.hybrid_fetcher import DataFetcher
from options_radar.market_clock import market_clock_state
from options_radar.microcap_hunter import assess_microcap_candidate
from options_radar.provider_preflight import install_provider_preflight
from options_radar.settings import Settings

# Install data acquisition before the institutional runner creates any fetchers.
# Unconfigured providers are removed before fan-out; single-flight then shares
# only concurrently overlapping identical fetches and never retains a completed
# stock response as a cross-request cache.
install_data_fabric()
install_provider_preflight()
install_data_fabric_singleflight()
from scripts import fast_explosion_scan_runner as runner  # noqa: E402

_original_rank = runner._rank_market_with_institutional_engine


def _regular_session_open(now: datetime | None = None) -> bool:
    try:
        return bool(market_clock_state(now).is_regular_open)
    except Exception:
        return False


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if pd.notna(result) else default


def _validate_candidate(fetcher: DataFetcher, candidate: Any) -> tuple[str, dict[str, Any]]:
    now = datetime.now(timezone.utc)
    try:
        result = fetcher.fetch_stock_bars(
            candidate.symbol,
            interval="5m",
            start=now - timedelta(days=3),
            end=now,
        )
        frame = result.data
        if frame is None or frame.empty:
            raise RuntimeError("empty reconciled stock bars")
        close_series = pd.to_numeric(frame["Close"], errors="coerce").dropna()
        latest = float(close_series.iloc[-1])
        latest_stamp = frame.index[-1] if len(frame.index) else None
        provider_quote_timestamp = None
        if isinstance(latest_stamp, pd.Timestamp) and latest_stamp.tzinfo is not None:
            provider_quote_timestamp = latest_stamp.to_pydatetime().astimezone(
                timezone.utc
            ).isoformat()

        average_volume_20d = 0.0
        daily_source = ""
        try:
            daily_result = fetcher.fetch_stock_bars(
                candidate.symbol,
                interval="1d",
                start=now - timedelta(days=60),
                end=now,
            )
            daily = daily_result.data
            daily_source = str(daily_result.source)
            if daily is not None and not daily.empty and "Volume" in daily:
                working = daily
                if isinstance(daily.index, pd.DatetimeIndex) and len(daily.index):
                    last_daily = daily.index[-1]
                    if last_daily.date() == now.date():
                        working = daily.iloc[:-1]
                volumes = pd.to_numeric(working["Volume"], errors="coerce").dropna()
                volumes = volumes[volumes > 0]
                if len(volumes):
                    average_volume_20d = float(volumes.tail(20).mean())
        except Exception:
            average_volume_20d = 0.0

        current_volume = _number(getattr(candidate, "volume", 0.0))
        rvol = current_volume / average_volume_20d if average_volume_20d > 0 else 0.0
        metadata = result.metadata or {} if hasattr(result, "metadata") else {}
        audit = metadata.get("data_fabric", {}) if isinstance(metadata, dict) else {}
        stream = metadata.get("stream_reference") if isinstance(metadata, dict) else None
        candidate_price = _number(getattr(candidate, "price", 0.0))
        divergence = (
            abs(candidate_price - latest) / latest
            if latest > 0 and candidate_price > 0
            else 0.0
        )
        return candidate.symbol, {
            "available": True,
            "selected_source": result.source,
            "daily_source": daily_source,
            "fabric_source_count": int(audit.get("source_count") or 0),
            "fabric_sources": list(audit.get("sources") or []),
            "fabric_consensus_pass": bool(audit.get("consensus_pass", True)),
            "fabric_latest_close": round(latest, 6),
            "provider_quote_timestamp": provider_quote_timestamp,
            "average_volume_20d": round(average_volume_20d, 2)
            if average_volume_20d > 0
            else None,
            "rvol": round(rvol, 4) if rvol > 0 else None,
            "rvol_source": (
                "Nasdaq cumulative session volume / prior 20 completed daily bars"
                if rvol > 0
                else ""
            ),
            "nasdaq_vs_fabric_divergence_pct": round(divergence, 6),
            "selected_close_divergence_pct": audit.get("selected_close_divergence_pct"),
            "stream_reference": stream if isinstance(stream, dict) else None,
            "health_checked": True,
        }
    except Exception as exc:
        return candidate.symbol, {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "health_checked": True,
        }


def _persist_validation(ranked: list[Any]) -> None:
    try:
        payload = json.loads(runner.FAST_MARKET_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    symbols = payload.get("symbols") if isinstance(payload.get("symbols"), dict) else {}
    for candidate in ranked:
        row = symbols.get(candidate.symbol)
        validation = getattr(candidate, "data_fabric_validation", None)
        if isinstance(row, dict) and isinstance(validation, dict):
            row["data_fabric_validation"] = validation
            if validation.get("provider_quote_timestamp"):
                row["provider_quote_timestamp"] = validation["provider_quote_timestamp"]
            if validation.get("average_volume_20d"):
                row["average_volume_20d"] = validation["average_volume_20d"]
            if validation.get("rvol"):
                row["rvol"] = validation["rvol"]
                row["rvol_source"] = validation.get("rvol_source") or ""
            row["microcap_hunter"] = assess_microcap_candidate(
                {"symbol": candidate.symbol, **row}
            ).as_dict()
            row["send_priority"] = round(
                float(
                    getattr(
                        candidate,
                        "institutional_priority",
                        row.get("send_priority", 0.0),
                    )
                ),
                2,
            )
    payload["data_fabric"] = {
        "enabled": True,
        "validation_scope": "top institutional stock candidates only",
        "signals_remain_independent_from_options": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    runner.base._save(runner.FAST_MARKET_STATE_PATH, payload)


def _rank_market_with_fabric(rows, news_events, structural):
    ranked = _original_rank(rows, news_events=news_events, structural=structural)
    if not ranked:
        return ranked

    maximum = max(
        3,
        min(30, int(os.getenv("DATA_FABRIC_STOCK_VALIDATION_TOP", "12"))),
    )
    selected = sorted(
        ranked,
        key=lambda item: (
            float(getattr(item, "institutional_priority", 0.0)),
            float(getattr(item, "score", 0.0)),
        ),
        reverse=True,
    )[:maximum]
    settings = Settings()
    fetcher = DataFetcher(settings)
    validations: dict[str, dict[str, Any]] = {}
    workers = max(1, min(4, len(selected)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_validate_candidate, fetcher, candidate): candidate.symbol
            for candidate in selected
        }
        for future in as_completed(futures):
            symbol, validation = future.result()
            validations[symbol] = validation

    regular = _regular_session_open()
    discovery_divergence = max(
        0.05,
        float(os.getenv("DATA_FABRIC_STOCK_DISCOVERY_DIVERGENCE_PCT", "0.08")),
    )
    for candidate in ranked:
        validation = validations.get(candidate.symbol)
        if validation is None:
            candidate.data_fabric_validation = {"available": False, "not_checked": True}
            continue
        candidate.data_fabric_validation = validation
        if not validation.get("available"):
            candidate.reasons.append("بيانات التحقق المتعدد غير متاحة؛ لا ترقية للثقة")
            continue
        sources = int(validation.get("fabric_source_count") or 0)
        divergence = _number(validation.get("nasdaq_vs_fabric_divergence_pct"))
        consensus = bool(validation.get("fabric_consensus_pass", True))
        if sources >= 2 and consensus:
            candidate.reasons.insert(
                1,
                f"Data Fabric: توافق {sources} مصادر مستقلة",
            )
            candidate.institutional_priority = min(
                100.0,
                float(
                    getattr(
                        candidate,
                        "institutional_priority",
                        candidate.score,
                    )
                )
                + 2.0,
            )
        if regular and sources >= 2 and divergence > discovery_divergence:
            candidate.reasons.append(
                f"تحذير بيانات: Nasdaq/Fabric مختلفان {divergence * 100:.1f}%"
            )
            # Microcaps can move several percent inside one 5-minute bucket. This
            # is a strong penalty, not an automatic invalidation of the stock path.
            candidate.institutional_priority = max(
                0.0,
                float(
                    getattr(
                        candidate,
                        "institutional_priority",
                        candidate.score,
                    )
                )
                - 12.0,
            )
        elif sources >= 2 and not consensus:
            candidate.reasons.append("حاجز بيانات: اختلاف واضح بين مزودي الأسعار")
            candidate.institutional_priority = max(
                0.0,
                float(
                    getattr(
                        candidate,
                        "institutional_priority",
                        candidate.score,
                    )
                )
                - 10.0,
            )

    _persist_validation(ranked)
    ranked.sort(
        key=lambda item: (
            runner.base.STAGE_ORDER.get(item.stage, 0),
            float(getattr(item, "institutional_priority", 0.0)),
            item.score,
            item.turnover_pct,
        ),
        reverse=True,
    )
    return ranked


runner.base.rank_market = _rank_market_with_fabric
runner.rank_market = _rank_market_with_fabric


def main() -> int:
    return runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
