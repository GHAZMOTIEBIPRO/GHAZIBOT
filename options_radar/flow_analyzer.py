from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
HistoryLoader = Callable[[str], Any]


@dataclass(frozen=True)
class FlowThresholds:
    min_volume: int = 200
    min_open_interest: int = 100
    min_vol_to_oi: float = 1.5
    high_accumulation_ratio: float = 3.0
    min_volume_spike_ratio: float = 2.0
    max_history_contracts: int = 45
    history_workers: int = 3
    require_volume_spike: bool = False


@dataclass
class FlowAnalysisResult:
    accepted: pd.DataFrame
    rejected: pd.DataFrame
    analyzed: pd.DataFrame
    summary: dict[str, Any]


class FlowAnalyzer:
    """Detect strict ask-side unusual options activity.

    The latest trade position inside the bid/ask spread is a buying-pressure proxy,
    not exchange-level proof of the initiating party. The detector therefore also
    requires strong volume, open interest, and Vol/OI evidence and publishes every
    component used by the decision.
    """

    def __init__(
        self,
        settings: Any | None = None,
        thresholds: FlowThresholds | None = None,
    ) -> None:
        if thresholds is not None:
            self.thresholds = thresholds
            return
        self.thresholds = FlowThresholds(
            min_volume=int(getattr(settings, "min_option_volume", 200)),
            min_open_interest=int(getattr(settings, "min_open_interest", 100)),
            min_vol_to_oi=float(getattr(settings, "min_vol_to_oi_ratio", 1.5)),
            high_accumulation_ratio=float(
                getattr(settings, "high_accumulation_ratio", 3.0)
            ),
            min_volume_spike_ratio=float(
                getattr(settings, "min_volume_spike_ratio", 2.0)
            ),
            max_history_contracts=int(
                getattr(settings, "flow_history_max_contracts", 45)
            ),
            history_workers=int(getattr(settings, "flow_history_workers", 3)),
            require_volume_spike=bool(
                getattr(settings, "flow_require_volume_spike", False)
            ),
        )

    @staticmethod
    def _safe_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
        if column not in frame:
            return pd.Series(np.nan, index=frame.index, dtype="float64")
        return pd.to_numeric(frame[column], errors="coerce")

    @staticmethod
    def _history_frame(value: Any) -> pd.DataFrame:
        if isinstance(value, pd.DataFrame):
            return value
        data = getattr(value, "data", None)
        if isinstance(data, pd.DataFrame):
            return data
        if isinstance(value, dict):
            candidate = value.get("data")
            if not isinstance(candidate, pd.DataFrame):
                candidate = value.get("frame")
            if isinstance(candidate, pd.DataFrame):
                return candidate
        return pd.DataFrame()

    @staticmethod
    def _prior_five_day_average(history: pd.DataFrame) -> float | None:
        if history is None or history.empty:
            return None
        volume_column = (
            "Volume"
            if "Volume" in history
            else "volume"
            if "volume" in history
            else None
        )
        if not volume_column:
            return None
        volume = pd.to_numeric(history[volume_column], errors="coerce")
        if isinstance(history.index, pd.DatetimeIndex):
            today = pd.Timestamp.now(tz="UTC").date()
            index = pd.to_datetime(history.index, utc=True, errors="coerce")
            volume = volume[index.date < today]
        else:
            # Drop a provider's latest row because it can be the current session
            # represented by the option-chain snapshot.
            volume = volume.iloc[:-1] if len(volume) > 1 else volume.iloc[0:0]
        prior = volume.dropna().clip(lower=0).tail(5)
        if prior.empty:
            return None
        average = float(prior.mean())
        return average if math.isfinite(average) and average > 0 else None

    def _load_volume_baselines(
        self,
        frame: pd.DataFrame,
        history_loader: HistoryLoader | None,
    ) -> dict[str, tuple[float | None, str | None]]:
        if history_loader is None or frame.empty:
            return {}
        ranked = frame.sort_values(
            ["vol_to_oi_ratio", "volume"], ascending=[False, False]
        ).head(max(0, self.thresholds.max_history_contracts))
        contracts = list(dict.fromkeys(ranked["contract_symbol"].astype(str)))
        if not contracts:
            return {}

        results: dict[str, tuple[float | None, str | None]] = {}
        workers = max(1, min(self.thresholds.history_workers, len(contracts)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(history_loader, contract): contract
                for contract in contracts
            }
            for future in as_completed(futures):
                contract = futures[future]
                try:
                    raw = future.result()
                    average = self._prior_five_day_average(self._history_frame(raw))
                    source = str(getattr(raw, "source", "") or "") or None
                    results[contract] = (average, source)
                except Exception as exc:
                    LOGGER.debug(
                        "Option volume history failed for %s: %s", contract, exc
                    )
                    results[contract] = (None, None)
        return results

    @staticmethod
    def _technical_component(side: str, technical_direction: str | None) -> float:
        direction = str(technical_direction or "neutral").lower()
        side = str(side or "").lower()
        if direction == "neutral":
            return 15.0
        if (side == "call" and direction == "bullish") or (
            side == "put" and direction == "bearish"
        ):
            return 25.0
        return 0.0

    @staticmethod
    def _contract_component(delta: float, dte: float) -> float:
        if not math.isfinite(delta) or not math.isfinite(dte):
            return 0.0
        delta_fit = max(0.0, 1.0 - abs(abs(delta) - 0.45) / 0.15)
        dte_fit = max(0.0, 1.0 - abs(dte - 35.0) / 25.0)
        return 15.0 * (0.65 * delta_fit + 0.35 * dte_fit)

    def analyze(
        self,
        chain: pd.DataFrame,
        *,
        technical_direction: str | None = None,
        history_loader: HistoryLoader | None = None,
    ) -> FlowAnalysisResult:
        if chain is None or chain.empty:
            empty = pd.DataFrame()
            return FlowAnalysisResult(
                empty,
                empty,
                empty,
                {
                    "analyzed": 0,
                    "accepted": 0,
                    "rejected": 0,
                    "aggressive_buying": 0,
                    "high_accumulation": 0,
                },
            )

        frame = chain.copy()
        for column in (
            "bid",
            "ask",
            "last",
            "volume",
            "open_interest",
            "delta",
            "dte",
        ):
            frame[column] = self._safe_numeric(frame, column)

        frame["mid"] = (frame["bid"] + frame["ask"]) / 2.0
        frame["spread"] = frame["ask"] - frame["bid"]
        frame["spread_pct"] = frame["spread"] / frame["ask"].replace(0, np.nan)
        frame["quote_position"] = (
            (frame["last"] - frame["bid"])
            / frame["spread"].replace(0, np.nan)
        ).clip(lower=0.0, upper=1.0)
        frame["ask_side_buying"] = (
            frame["last"].notna()
            & frame["mid"].notna()
            & (frame["last"] >= frame["mid"])
        )

        frame["vol_to_oi_ratio"] = np.where(
            frame["open_interest"] > 0,
            frame["volume"] / frame["open_interest"],
            np.nan,
        )
        frame["vol_to_oi_ratio"] = pd.to_numeric(
            frame["vol_to_oi_ratio"], errors="coerce"
        ).replace([np.inf, -np.inf], np.nan)
        # Backward-compatible alias used by Phase 4 scoring and UI code.
        frame["vol_oi"] = frame["vol_to_oi_ratio"]
        frame["high_accumulation"] = (
            frame["vol_to_oi_ratio"]
            >= self.thresholds.high_accumulation_ratio
        )
        frame["accumulation_tier"] = np.select(
            [
                frame["high_accumulation"],
                frame["vol_to_oi_ratio"] >= self.thresholds.min_vol_to_oi,
            ],
            ["High Accumulation", "Elevated Accumulation"],
            default="Normal",
        )

        frame["buying_flow_type"] = np.select(
            [
                frame["ask_side_buying"]
                & (
                    (frame["quote_position"] >= 0.75)
                    | frame["high_accumulation"]
                ),
                frame["ask_side_buying"],
            ],
            ["Aggressive Buying", "Moderate Buying"],
            default="Neutral",
        )
        frame["aggressor_proxy"] = np.select(
            [
                frame["quote_position"] >= 0.75,
                frame["quote_position"] >= 0.50,
            ],
            ["ask", "mid"],
            default="bid",
        )

        prehistory = frame[
            (frame["volume"] >= self.thresholds.min_volume)
            & (frame["open_interest"] >= self.thresholds.min_open_interest)
            & (
                frame["vol_to_oi_ratio"]
                >= self.thresholds.min_vol_to_oi
            )
            & frame["ask_side_buying"]
        ].copy()
        if "quality_passed" in prehistory:
            prehistory = prehistory[
                prehistory["quality_passed"].fillna(False)
            ]

        baselines = self._load_volume_baselines(prehistory, history_loader)
        contracts = frame["contract_symbol"].astype(str)
        frame["prior_5d_avg_volume"] = contracts.map(
            lambda contract: baselines.get(contract, (None, None))[0]
        )
        frame["volume_history_source"] = contracts.map(
            lambda contract: baselines.get(contract, (None, None))[1]
        )
        prior_average = pd.to_numeric(
            frame["prior_5d_avg_volume"], errors="coerce"
        )
        frame["volume_spike_ratio"] = np.where(
            prior_average > 0,
            frame["volume"] / prior_average,
            np.nan,
        )
        frame["volume_spike_flag"] = (
            frame["volume_spike_ratio"]
            >= self.thresholds.min_volume_spike_ratio
        )

        base_eligibility = (
            (frame["volume"] >= self.thresholds.min_volume)
            & (frame["open_interest"] >= self.thresholds.min_open_interest)
            & (
                frame["vol_to_oi_ratio"]
                >= self.thresholds.min_vol_to_oi
            )
            & frame["ask_side_buying"]
        )
        if "quality_passed" in frame:
            base_eligibility &= frame["quality_passed"].fillna(False)

        unusual_confirmation = (
            frame["volume_spike_flag"] | frame["high_accumulation"]
        )
        if self.thresholds.require_volume_spike:
            unusual_confirmation = frame["volume_spike_flag"]
        frame["unusual_activity_flag"] = (
            base_eligibility & unusual_confirmation
        )
        frame["flow_gate_pass"] = frame["unusual_activity_flag"]

        ratio_strength = (
            (frame["vol_to_oi_ratio"] - self.thresholds.min_vol_to_oi)
            / max(6.0 - self.thresholds.min_vol_to_oi, 0.1)
        ).clip(lower=0.0, upper=1.0).fillna(0.0)
        spike_strength = (
            (frame["volume_spike_ratio"] - 1.0) / 4.0
        ).clip(lower=0.0, upper=1.0).fillna(0.0)
        frame["flow_volume_score"] = (
            28.0 * ratio_strength + 12.0 * spike_strength
        )
        frame["ask_aggression_score"] = (
            20.0 * ((frame["quote_position"] - 0.50) / 0.50)
        ).clip(lower=0.0, upper=20.0).fillna(0.0)
        frame["flow_technical_score"] = [
            self._technical_component(side, technical_direction)
            for side in frame["option_type"].astype(str)
        ]
        frame["flow_contract_score"] = [
            self._contract_component(float(delta), float(dte))
            if pd.notna(delta) and pd.notna(dte)
            else 0.0
            for delta, dte in zip(
                frame["delta"], frame["dte"], strict=False
            )
        ]
        frame["flow_momentum_score"] = (
            frame["flow_volume_score"]
            + frame["ask_aggression_score"]
            + frame["flow_technical_score"]
            + frame["flow_contract_score"]
        ).clip(lower=0.0, upper=100.0).round(4)

        def rejection_reason(row: pd.Series) -> str:
            existing = str(row.get("rejection_reason") or "").strip()
            if existing:
                return existing
            if (
                pd.isna(row.get("bid"))
                or pd.isna(row.get("ask"))
                or row["ask"] <= row["bid"]
            ):
                return "invalid_bid_ask"
            if pd.isna(row.get("last")):
                return "missing_last_trade"
            if (
                float(row.get("volume", 0) or 0)
                < self.thresholds.min_volume
            ):
                return "option_volume_below_200"
            if (
                float(row.get("open_interest", 0) or 0)
                < self.thresholds.min_open_interest
            ):
                return "open_interest_below_100"
            ratio = row.get("vol_to_oi_ratio")
            if (
                pd.isna(ratio)
                or float(ratio) < self.thresholds.min_vol_to_oi
            ):
                return "vol_to_oi_below_1_5"
            if not bool(row.get("ask_side_buying")):
                return "bid_side_or_neutral_trade"
            if (
                self.thresholds.require_volume_spike
                and not bool(row.get("volume_spike_flag"))
            ):
                return "volume_spike_below_200pct"
            if (
                not bool(row.get("volume_spike_flag"))
                and not bool(row.get("high_accumulation"))
            ):
                return "no_confirmed_unusual_volume"
            return ""

        frame["flow_rejection_reason"] = frame.apply(
            rejection_reason, axis=1
        )
        existing_rejection = frame.get(
            "rejection_reason", pd.Series("", index=frame.index)
        ).fillna("").astype(str)
        frame["rejection_reason"] = np.where(
            existing_rejection.str.len() > 0,
            existing_rejection,
            frame["flow_rejection_reason"],
        )

        accepted = frame[frame["flow_gate_pass"]].copy().sort_values(
            [
                "flow_momentum_score",
                "vol_to_oi_ratio",
                "volume_spike_ratio",
                "volume",
            ],
            ascending=[False, False, False, False],
            na_position="last",
        )
        rejected = frame[~frame["flow_gate_pass"]].copy()
        summary = {
            "analyzed": int(len(frame)),
            "accepted": int(len(accepted)),
            "rejected": int(len(rejected)),
            "aggressive_buying": int(
                (frame["buying_flow_type"] == "Aggressive Buying").sum()
            ),
            "moderate_buying": int(
                (frame["buying_flow_type"] == "Moderate Buying").sum()
            ),
            "high_accumulation": int(frame["high_accumulation"].sum()),
            "volume_spikes": int(frame["volume_spike_flag"].sum()),
            "history_enriched": int(
                frame["prior_5d_avg_volume"].notna().sum()
            ),
        }
        return FlowAnalysisResult(accepted, rejected, frame, summary)

    @staticmethod
    def top_by_side(
        frame: pd.DataFrame,
        limit: int = 15,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        if frame is None or frame.empty:
            columns = list(frame.columns) if isinstance(frame, pd.DataFrame) else None
            empty = pd.DataFrame(columns=columns)
            return empty.copy(), empty.copy()
        sort_columns = [
            column
            for column in (
                "flow_rank_score",
                "flow_momentum_score",
                "score",
                "vol_to_oi_ratio",
                "volume_spike_ratio",
                "volume",
            )
            if column in frame.columns
        ]
        ordered = frame.sort_values(
            sort_columns,
            ascending=[False] * len(sort_columns),
            na_position="last",
        )
        side = ordered["option_type"].astype(str).str.lower()
        calls = ordered[side.eq("call")].head(limit).copy()
        puts = ordered[side.eq("put")].head(limit).copy()
        return calls.reset_index(drop=True), puts.reset_index(drop=True)
