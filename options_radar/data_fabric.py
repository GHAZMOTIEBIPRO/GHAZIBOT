from __future__ import annotations

import json
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class FabricAttempt:
    provider: str
    operation: str
    success: bool
    elapsed_ms: int
    rows: int = 0
    error: str | None = None
    skipped_by_circuit: bool = False


@dataclass(frozen=True)
class FabricFetch:
    provider: str
    value: Any
    attempt: FabricAttempt


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _utc(value: Any | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        return datetime.now(timezone.utc)
    return stamp.to_pydatetime().astimezone(timezone.utc)


def _provider_family(provider: str) -> str:
    name = str(provider or "").lower()
    if "yahoo" in name or "yfinance" in name:
        return "yahoo"
    if "tradier" in name:
        return "tradier"
    if "marketdata" in name:
        return "marketdata"
    if "alpaca" in name:
        return "alpaca"
    if "finnhub" in name:
        return "finnhub"
    if "tiingo" in name:
        return "tiingo"
    if "twelve" in name:
        return "twelve_data"
    if "polygon" in name or "massive" in name:
        return "polygon_massive"
    if "alpha" in name:
        return "alpha_vantage"
    if "databento" in name:
        return "databento"
    return name or "unknown"


def _source_tier(provider: str, freshness: str = "") -> str:
    text = f"{provider} {freshness}".lower()
    if any(token in text for token in ("sandbox", "delayed", "indicative", "unofficial", "may be delayed", "24h")):
        return "DELAYED_OR_INDICATIVE"
    if any(token in text for token in ("opra", "sip", "brokerage feed", "licensed", "real-time", "realtime")):
        return "LIVE_OR_LICENSED"
    if any(token in text for token in ("account", "entitlement", "iex")):
        return "ACCOUNT_FEED"
    return "UNKNOWN"


class ProviderHealthRegistry:
    """Small persistent circuit breaker for external data providers.

    It does not decide trading direction. It only prevents repeated calls to a
    provider that is demonstrably failing and records latency/reliability for
    audit. State is intentionally simple JSON so GitHub Actions can restore it.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        failure_threshold: int = 3,
        cool_down_minutes: int = 20,
    ) -> None:
        self.path = Path(path)
        self.failure_threshold = max(2, int(failure_threshold))
        self.cool_down = timedelta(minutes=max(5, int(cool_down_minutes)))
        self._lock = threading.Lock()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("schema_version", 1)
        payload.setdefault("updated_at", None)
        payload.setdefault("providers", {})
        return payload

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state["updated_at"] = datetime.now(timezone.utc).isoformat()
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def _key(self, provider: str, operation: str) -> str:
        return f"{_provider_family(provider)}:{operation}"

    def allowed(self, provider: str, operation: str, now: datetime | None = None) -> bool:
        now = _utc(now)
        row = self._state.get("providers", {}).get(self._key(provider, operation), {})
        opened_at = row.get("circuit_opened_at") if isinstance(row, dict) else None
        if not opened_at:
            return True
        try:
            opened = _utc(opened_at)
        except Exception:
            return True
        return now - opened >= self.cool_down

    def record(self, attempt: FabricAttempt) -> None:
        key = self._key(attempt.provider, attempt.operation)
        with self._lock:
            providers = self._state.setdefault("providers", {})
            row = providers.setdefault(
                key,
                {
                    "provider": _provider_family(attempt.provider),
                    "operation": attempt.operation,
                    "successes": 0,
                    "failures": 0,
                    "consecutive_failures": 0,
                    "latency_ema_ms": None,
                    "last_success_at": None,
                    "last_failure_at": None,
                    "last_error": None,
                    "circuit_opened_at": None,
                },
            )
            latency = max(0, int(attempt.elapsed_ms))
            previous = row.get("latency_ema_ms")
            row["latency_ema_ms"] = latency if previous is None else round(0.75 * _number(previous) + 0.25 * latency, 2)
            now = datetime.now(timezone.utc).isoformat()
            if attempt.success:
                row["successes"] = int(row.get("successes", 0)) + 1
                row["consecutive_failures"] = 0
                row["last_success_at"] = now
                row["last_error"] = None
                row["circuit_opened_at"] = None
            elif not attempt.skipped_by_circuit:
                row["failures"] = int(row.get("failures", 0)) + 1
                row["consecutive_failures"] = int(row.get("consecutive_failures", 0)) + 1
                row["last_failure_at"] = now
                row["last_error"] = attempt.error
                if int(row["consecutive_failures"]) >= self.failure_threshold:
                    row["circuit_opened_at"] = now
            self._save()

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._state))


def parallel_fetch(
    loaders: dict[str, Callable[[], Any]],
    *,
    operation: str,
    row_counter: Callable[[Any], int],
    health: ProviderHealthRegistry | None = None,
    max_workers: int = 4,
) -> list[FabricFetch]:
    """Fetch independent providers concurrently with failure isolation."""
    import time

    output: list[FabricFetch] = []
    runnable: dict[str, Callable[[], Any]] = {}
    for provider, loader in loaders.items():
        if health is not None and not health.allowed(provider, operation):
            attempt = FabricAttempt(
                provider=provider,
                operation=operation,
                success=False,
                elapsed_ms=0,
                error="circuit_open",
                skipped_by_circuit=True,
            )
            output.append(FabricFetch(provider, None, attempt))
            continue
        runnable[provider] = loader

    def execute(provider: str, loader: Callable[[], Any]) -> FabricFetch:
        started = time.perf_counter()
        try:
            value = loader()
            rows = max(0, int(row_counter(value)))
            success = value is not None and rows > 0
            error = None if success else "empty response"
        except Exception as exc:  # provider isolation is the point of this layer
            value = None
            rows = 0
            success = False
            error = f"{type(exc).__name__}: {exc}"
        attempt = FabricAttempt(
            provider=provider,
            operation=operation,
            success=success,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            rows=rows,
            error=error,
        )
        return FabricFetch(provider, value, attempt)

    if runnable:
        workers = max(1, min(int(max_workers), len(runnable)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(execute, name, loader): name for name, loader in runnable.items()}
            for future in as_completed(futures):
                output.append(future.result())

    for item in output:
        if health is not None:
            health.record(item.attempt)
    order = {name: idx for idx, name in enumerate(loaders)}
    output.sort(key=lambda item: order.get(item.provider, 999))
    return output


def _valid_quote(row: pd.Series | dict[str, Any]) -> bool:
    bid = _number(row.get("bid"), float("nan"))
    ask = _number(row.get("ask"), float("nan"))
    return math.isfinite(bid) and math.isfinite(ask) and bid > 0 and ask >= bid


def _quote_mid(row: pd.Series | dict[str, Any]) -> float:
    if not _valid_quote(row):
        return float("nan")
    return (_number(row.get("bid")) + _number(row.get("ask"))) / 2.0


def _latest_age_seconds(value: Any) -> float | None:
    stamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(stamp):
        return None
    return max(0.0, (pd.Timestamp.now(tz="UTC") - stamp).total_seconds())


def reconcile_option_chains(
    frames: dict[str, pd.DataFrame],
    *,
    freshness: dict[str, str] | None = None,
    max_quote_divergence_pct: float = 0.08,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Merge exact OCC contracts without manufacturing a synthetic NBBO.

    Bid/ask always stay paired from one provider. Other fields may be filled from
    another exact-contract row, with field provenance recorded. Cross-provider
    midpoint disagreement is measured and can only reduce confidence.
    """
    freshness = freshness or {}
    parts: list[pd.DataFrame] = []
    for provider, frame in frames.items():
        if frame is None or frame.empty:
            continue
        part = frame.copy()
        part["_fabric_provider"] = provider
        part["_fabric_freshness"] = freshness.get(provider, "")
        parts.append(part)
    if not parts:
        return pd.DataFrame(), {"source_count": 0, "contracts": 0, "consensus_contracts": 0}

    combined = pd.concat(parts, ignore_index=True, sort=False)
    combined = combined.dropna(subset=["contract_symbol"])
    combined["contract_symbol"] = combined["contract_symbol"].astype(str).str.upper().str.replace(" ", "", regex=False)
    combined["data_quality"] = pd.to_numeric(combined.get("data_quality"), errors="coerce").fillna(0.0)

    rows: list[pd.Series] = []
    divergences: list[float] = []
    consensus_contracts = 0
    for _, group in combined.groupby("contract_symbol", sort=False):
        group = group.copy()
        group["_mid"] = group.apply(_quote_mid, axis=1)
        group["_age"] = group.get("updated_at", pd.Series(index=group.index, dtype=object)).map(_latest_age_seconds)
        group["_recency_bonus"] = group["_age"].map(lambda value: 0.03 if value is not None and value <= 120 else 0.0)
        group["_rank"] = group["data_quality"] + group["_recency_bonus"]
        quote_rows = group[group.apply(_valid_quote, axis=1)].sort_values(["_rank", "data_quality"], ascending=False)
        base = (quote_rows.iloc[0] if not quote_rows.empty else group.sort_values("_rank", ascending=False).iloc[0]).copy()

        valid_mids = [float(value) for value in group["_mid"].dropna() if math.isfinite(float(value)) and float(value) > 0]
        divergence = 0.0
        if len(valid_mids) >= 2:
            centre = median(valid_mids)
            divergence = (max(valid_mids) - min(valid_mids)) / centre if centre > 0 else 0.0
            divergences.append(divergence)
            consensus_contracts += 1
        provider_names = list(dict.fromkeys(str(value) for value in group["_fabric_provider"] if str(value)))
        families = list(dict.fromkeys(_provider_family(value) for value in provider_names))
        quote_provider = str(base.get("_fabric_provider") or "")
        field_sources: dict[str, str] = {"bid": quote_provider, "ask": quote_provider, "last": quote_provider}

        for column in (
            "volume",
            "open_interest",
            "iv",
            "delta",
            "gamma",
            "theta",
            "vega",
            "underlying_price",
            "updated_at",
            "expiration",
            "strike",
            "option_type",
            "symbol",
            "greeks_method",
        ):
            value = base.get(column)
            missing = value is None or (isinstance(value, float) and math.isnan(value)) or (column in {"volume", "open_interest"} and _number(value) <= 0)
            if not missing or column not in group:
                if not missing:
                    field_sources.setdefault(column, quote_provider)
                continue
            candidates = group.copy()
            candidates["_present"] = candidates[column].map(
                lambda item: item is not None and not (isinstance(item, float) and math.isnan(item)) and (column not in {"volume", "open_interest"} or _number(item) > 0)
            )
            candidates = candidates[candidates["_present"]].sort_values("_rank", ascending=False)
            if not candidates.empty:
                chosen = candidates.iloc[0]
                base[column] = chosen[column]
                field_sources[column] = str(chosen.get("_fabric_provider") or "")

        best_quality = _number(base.get("data_quality"))
        if len(valid_mids) >= 2 and divergence > max_quote_divergence_pct:
            best_quality *= max(0.45, 1.0 - min(0.5, divergence * 2.5))
        source_count = len(provider_names)
        if len(valid_mids) >= 2:
            agreement = max(0.0, 1.0 - divergence / max(max_quote_divergence_pct, 1e-6))
            consensus_score = 55.0 + 45.0 * agreement
        else:
            consensus_score = 45.0 if source_count == 1 else 52.0

        base["data_quality"] = round(min(1.0, best_quality), 4)
        base["fabric_sources"] = ",".join(provider_names)
        base["fabric_source_count"] = source_count
        base["fabric_independent_source_count"] = len(families)
        base["fabric_quote_provider"] = quote_provider
        base["fabric_quote_divergence_pct"] = round(divergence, 6)
        base["fabric_quote_consensus_score"] = round(consensus_score, 2)
        base["fabric_consensus_pass"] = bool(len(valid_mids) < 2 or divergence <= max_quote_divergence_pct)
        base["fabric_field_sources"] = json.dumps(field_sources, sort_keys=True)
        base["fabric_source_tier"] = _source_tier(quote_provider, str(base.get("_fabric_freshness") or base.get("freshness_label") or ""))
        base["source"] = " + ".join(provider_names)
        freshness_labels = list(dict.fromkeys(str(value) for value in group.get("freshness_label", pd.Series(dtype=str)).dropna() if str(value)))
        if freshness_labels:
            base["freshness_label"] = " | ".join(freshness_labels)
        rows.append(base)

    result = pd.DataFrame(rows)
    drop_columns = [column for column in result.columns if column.startswith("_fabric_") or column in {"_mid", "_age", "_recency_bonus", "_rank", "_present"}]
    result = result.drop(columns=drop_columns, errors="ignore").reset_index(drop=True)
    audit = {
        "source_count": len(frames),
        "sources": list(frames),
        "contracts": len(result),
        "consensus_contracts": consensus_contracts,
        "median_quote_divergence_pct": round(float(median(divergences)), 6) if divergences else None,
        "max_quote_divergence_pct": round(max(divergences), 6) if divergences else None,
        "policy": "exact-contract reconciliation; bid/ask pair never synthesized across providers",
    }
    return result, audit


def reconcile_stock_bars(
    frames: dict[str, pd.DataFrame],
    *,
    freshness: dict[str, str] | None = None,
    max_close_divergence_pct: float = 0.025,
) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    """Choose one complete bar series, using other providers only as validation."""
    freshness = freshness or {}
    candidates: list[dict[str, Any]] = []
    static_quality = {
        "tradier": 0.90,
        "alpaca": 0.88,
        "tiingo": 0.84,
        "finnhub": 0.80,
        "twelve_data": 0.70,
        "polygon": 0.68,
        "alpha_vantage": 0.62,
        "yahoo": 0.52,
        "yfinance": 0.52,
    }
    for provider, frame in frames.items():
        if frame is None or frame.empty or "Close" not in frame:
            continue
        clean = frame.dropna(subset=["Close"]).sort_index()
        if clean.empty:
            continue
        latest = clean.iloc[-1]
        latest_at = clean.index[-1]
        candidates.append(
            {
                "provider": provider,
                "frame": clean,
                "close": _number(latest.get("Close")),
                "latest_at": pd.to_datetime(latest_at, utc=True, errors="coerce"),
                "quality": static_quality.get(_provider_family(provider), 0.60),
                "rows": len(clean),
            }
        )
    if not candidates:
        return pd.DataFrame(), "", {"source_count": 0}

    valid_closes = [item["close"] for item in candidates if item["close"] > 0]
    centre = median(valid_closes) if valid_closes else 0.0
    for item in candidates:
        divergence = abs(item["close"] - centre) / centre if centre > 0 and item["close"] > 0 else 1.0
        item["close_divergence_pct"] = divergence
        item["score"] = item["quality"] - min(0.45, divergence * 3.0)
        tier = _source_tier(item["provider"], freshness.get(item["provider"], ""))
        if tier == "DELAYED_OR_INDICATIVE":
            item["score"] -= 0.05
    candidates.sort(key=lambda item: (item["score"], item["rows"]), reverse=True)
    chosen = candidates[0]
    audit = {
        "source_count": len(candidates),
        "sources": [item["provider"] for item in candidates],
        "selected_source": chosen["provider"],
        "latest_close": chosen["close"],
        "median_latest_close": round(centre, 6) if centre > 0 else None,
        "selected_close_divergence_pct": round(chosen["close_divergence_pct"], 6),
        "max_close_divergence_pct": round(max(item["close_divergence_pct"] for item in candidates), 6),
        "consensus_pass": bool(len(candidates) < 2 or chosen["close_divergence_pct"] <= max_close_divergence_pct),
        "policy": "select one intact series; other feeds validate latest close only",
    }
    return chosen["frame"], chosen["provider"], audit


def health_from_env() -> ProviderHealthRegistry:
    return ProviderHealthRegistry(
        Path(os.getenv("DATA_FABRIC_HEALTH_PATH", "data/live/provider_health.json")),
        failure_threshold=int(os.getenv("DATA_FABRIC_CIRCUIT_FAILURES", "3")),
        cool_down_minutes=int(os.getenv("DATA_FABRIC_CIRCUIT_MINUTES", "20")),
    )
