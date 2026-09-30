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
        close = pd.to_numeric(frame["Close"], errors="coerce")
        high = pd.to_numeric(frame.get("High", frame["Close"]), errors="coerce")
        low = pd.to_numeric(frame.get("Low", frame["Close"]), errors="coerce")
        volume = pd.to_numeric(frame.get("Volume", pd.Series(index=frame.index, dtype=float)), errors="coerce")
        clean = pd.DataFrame({"close": close, "high": high, "low": low, "volume": volume}).dropna(subset=["close"])
        latest = float(clean["close"].iloc[-1])
        chart_quality = {}
        if len(clean) >= 12:
            recent = clean.tail(6)
            prior = clean.iloc[-12:-6]
            prior_high = float(prior["high"].max()) if not prior.empty else latest
            recent_range = float((recent["high"] - recent["low"]).mean())
            prior_range = float((prior["high"] - prior["low"]).mean())
            compression_ratio = recent_range / prior_range if prior_range > 0 else 1.0
            resistance_distance_pct = max(0.0, (prior_high - latest) / latest * 100.0) if latest > 0 else 0.0
            prior_volume = float(prior["volume"].median()) if prior["volume"].notna().any() else 0.0
            last_volume = float(recent["volume"].iloc[-1]) if recent["volume"].notna().any() else 0.0
            volume_acceleration = last_volume / prior_volume if prior_volume > 0 else 1.0
            chart_quality = {"bars_used": len(clean), "compression_ratio": round(compression_ratio, 4), "resistance_distance_pct": round(resistance_distance_pct, 4), "volume_acceleration_ratio": round(volume_acceleration, 4), "compression_detected": compression_ratio <= 0.72, "near_breakout": 0 <= resistance_distance_pct <= 3.0, "volume_acceleration_detected": volume_acceleration >= 1.8}
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
            "fabric_source_count": int(audit.get("source_count") or 0),
            "fabric_sources": list(audit.get("sources") or []),
            "fabric_consensus_pass": bool(audit.get("consensus_pass", True)),
            "fabric_latest_close": round(latest, 6),
            "nasdaq_vs_fabric_divergence_pct": round(divergence, 6),
            "selected_close_divergence_pct": audit.get("selected_close_divergence_pct"),
            "stream_reference": stream if isinstance(stream, dict) else None,
            "chart_quality": chart_quality,
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
        chart = validation.get("chart_quality") if isinstance(validation.get("chart_quality"), dict) else {}
        compression = _number(chart.get("compression_ratio"), 1.0)
        resistance = _number(chart.get("resistance_distance_pct"), 99.0)
        volume_accel = _number(chart.get("volume_acceleration_ratio"), 1.0)
        pre_score = 0.0
        if compression <= 0.72:
            candidate.reasons.append(f"انضغاط شموع 5m: {compression:.2f} من النطاق السابق")
            pre_score += 5.0
        if 0 <= resistance <= 3.0:
            candidate.reasons.append(f"قريب من مقاومة سابقة: {resistance:.2f}%")
            pre_score += 5.0
        if volume_accel >= 1.8:
            candidate.reasons.append(f"تسارع حجم آخر شمعة: ×{volume_accel:.2f}")
            pre_score += 5.0
        if pre_score:
            candidate.score = min(100.0, float(candidate.score) + pre_score)
            candidate.institutional_priority = min(100.0, float(getattr(candidate, "institutional_priority", candidate.score)) + pre_score * 0.8)
        candidate.pre_explosion_score = round(min(100.0, pre_score * 6.67 + float(getattr(candidate, "institutional_earlyness", 0.0)) * 0.55), 2)

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
