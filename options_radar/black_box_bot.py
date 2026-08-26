from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .catalysts import CatalystScanner
from .providers import load_universe
from .scanner import OptionsRadar
from .settings import Settings
from .stocks import StockRadar

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BotConfig:
    enabled: bool = os.getenv("BLACK_BOX_BOT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    scan_minutes: int = int(os.getenv("BLACK_BOX_SCAN_MINUTES", "15"))
    top_stocks: int = int(os.getenv("BLACK_BOX_TOP_STOCKS", "20"))
    top_options: int = int(os.getenv("BLACK_BOX_TOP_OPTIONS", "15"))
    universe_path: str = os.getenv("BLACK_BOX_UNIVERSE", "data/universe.txt")
    telegram_token: str | None = os.getenv("TELEGRAM_BOT_TOKEN") or None
    telegram_chat_id: str | None = os.getenv("TELEGRAM_CHAT_ID") or None
    state_path: Path = Path(os.getenv("BLACK_BOX_BOT_STATE", "data/live/black_box_bot_state.json"))


class TelegramNotifier:
    def __init__(self, token: str | None, chat_id: str | None):
        self.token = token
        self.chat_id = chat_id
        self.session = requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.configured:
            LOGGER.info("Telegram is not configured; notification retained in server logs")
            return False
        response = self.session.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={
                "chat_id": self.chat_id,
                "text": text[:4096],
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        response.raise_for_status()
        return True


class EventLedger:
    """Durable de-duplication ledger for BLACK BOX scanner notifications."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._seen: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                self._seen = dict(payload.get("seen", {}))
        except Exception as exc:  # noqa: BLE001 - state corruption must fail soft
            LOGGER.warning("Could not load bot ledger %s: %s", self.path, exc)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"seen": self._seen}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def first_time(self, namespace: str, payload: Any) -> bool:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        key = f"{namespace}:{digest}"
        with self._lock:
            if key in self._seen:
                return False
            self._seen[key] = datetime.now(timezone.utc).isoformat()
            if len(self._seen) > 5000:
                self._seen = dict(list(self._seen.items())[-3500:])
            self._save()
        return True


class BlackBoxBot:
    """Standalone market/catalyst/options monitor.

    BLACK BOX does not consume TradingView or indicator signals and never submits
    broker orders. Its job is evidence aggregation, ranking and notification.
    """

    OPTION_HORIZONS = (
        ("يومي", 0, 2),
        ("أسبوعي", 3, 10),
        ("شهري", 11, 45),
    )

    def __init__(self, settings: Settings | None = None, config: BotConfig | None = None):
        self.settings = settings or Settings()
        self.config = config or BotConfig()
        self.notifier = TelegramNotifier(self.config.telegram_token, self.config.telegram_chat_id)
        self.ledger = EventLedger(self.config.state_path)
        self._last_snapshot: dict[str, Any] = {}
        self._scan_lock = threading.Lock()

    @property
    def last_snapshot(self) -> dict[str, Any]:
        return self._last_snapshot

    def _symbols(self) -> list[str]:
        symbols = load_universe(self.config.universe_path)
        return list(dict.fromkeys(str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()))

    @staticmethod
    def _safe(value: Any, default: str = "-") -> str:
        if value is None:
            return default
        try:
            if pd.isna(value):
                return default
        except Exception:  # noqa: BLE001 - arbitrary display value
            pass
        return str(value)

    def _notify_news(self, catalysts: pd.DataFrame) -> int:
        if catalysts.empty:
            return 0
        sent = 0
        rows = catalysts.reindex(catalysts["score"].abs().sort_values(ascending=False).index).head(30)
        for _, row in rows.iterrows():
            score = float(row.get("score", 0) or 0)
            if abs(score) < 30:
                continue
            identity = {
                "symbol": self._safe(row.get("symbol")),
                "headline": self._safe(row.get("headline")),
                "event_date": self._safe(row.get("event_date")),
                "source": self._safe(row.get("source")),
            }
            if not self.ledger.first_time("news", identity):
                continue
            direction = "إيجابي" if score > 0 else "سلبي"
            self.notifier.send(
                "\n".join(
                    [
                        "📰 بلاك بوكس | خبر جوهري",
                        f"السهم: {identity['symbol']}",
                        f"التقييم: {direction}",
                        f"الخبر: {identity['headline']}",
                        f"الفئة: {self._safe(row.get('category'))}",
                        f"المصدر: {identity['source']}",
                        f"الدليل: {self._safe(row.get('evidence'))}",
                    ]
                )
            )
            sent += 1
        return sent

    def _notify_options(self, frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        candidates = frame.copy()
        if "new_setup_candidate" in candidates:
            candidates = candidates[candidates["new_setup_candidate"] == True]  # noqa: E712
        candidates = candidates.sort_values("score", ascending=False).head(self.config.top_options * 3)
        sent = 0
        for _, row in candidates.iterrows():
            identity = {
                "contract": self._safe(row.get("contract_symbol")),
                "volume": int(float(row.get("volume", 0) or 0)),
                "oi": int(float(row.get("open_interest", 0) or 0)),
                "horizon": self._safe(row.get("horizon")),
            }
            if not identity["contract"] or identity["contract"] == "-":
                continue
            if not self.ledger.first_time("option", identity):
                continue
            option_type = self._safe(row.get("option_type")).upper()
            side_ar = "كول" if option_type == "CALL" else "بوت" if option_type == "PUT" else option_type
            self.notifier.send(
                "\n".join(
                    [
                        "🎯 بلاك بوكس | رصد عقد",
                        f"السهم: {self._safe(row.get('symbol'))}",
                        f"المدة: {identity['horizon']}",
                        f"العقد: {side_ar} | {self._safe(row.get('strike'))} | {self._safe(row.get('expiration'))[:10]}",
                        f"الحجم: {identity['volume']:,} | OI: {identity['oi']:,}",
                        f"دلتا: {self._safe(row.get('delta'))} | IV: {self._safe(row.get('iv'))}",
                        f"المحفز: {self._safe(row.get('catalyst'))}",
                        f"البيانات: {self._safe(row.get('source'))} — {self._safe(row.get('freshness_label'))}",
                        "تنبيه رصد وليس أمر تنفيذ.",
                    ]
                )
            )
            sent += 1
        return sent

    def _scan_option_horizons(
        self,
        option_symbols: list[str],
        catalysts: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict[str, str], dict[str, int]]:
        frames: list[pd.DataFrame] = []
        providers: dict[str, str] = {}
        counts: dict[str, int] = {}
        for label, min_dte, max_dte in self.OPTION_HORIZONS:
            horizon_settings = replace(self.settings, free_swing_mode=False, min_dte=min_dte, max_dte=max_dte)
            result = OptionsRadar(horizon_settings).scan(
                option_symbols,
                top=self.config.top_options,
                output_csv=f"results/options_{label}_latest.csv",
                catalysts=catalysts,
            )
            frame = result.opportunities.copy()
            if not frame.empty:
                frame["horizon"] = label
                frames.append(frame)
            providers[label] = result.provider
            counts[label] = int(len(frame))
        combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
        if not combined.empty:
            combined = combined.sort_values("score", ascending=False)
            Path("results").mkdir(parents=True, exist_ok=True)
            combined.to_csv("results/options_all_horizons_latest.csv", index=False)
        return combined, providers, counts

    def scan_once(self) -> dict[str, Any]:
        if not self._scan_lock.acquire(blocking=False):
            return {"status": "busy", **self._last_snapshot}
        started = datetime.now(timezone.utc)
        try:
            symbols = self._symbols()
            catalysts = CatalystScanner(self.settings).scan(symbols, lookback_days=3)
            stock_result = StockRadar(self.settings).scan(
                symbols,
                catalysts=catalysts,
                top=max(self.config.top_stocks, 10),
                output_csv="results/stocks_latest.csv",
            )
            option_symbols = (
                stock_result.opportunities["symbol"].head(max(20, self.config.top_stocks)).tolist()
                if not stock_result.opportunities.empty
                else symbols[: max(20, self.config.top_stocks)]
            )
            option_frame, option_providers, option_counts = self._scan_option_horizons(option_symbols, catalysts)
            self._last_snapshot = {
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbols": len(symbols),
                "market_regime": stock_result.regime,
                "stock_candidates": int(len(stock_result.opportunities)),
                "option_candidates": int(len(option_frame)),
                "option_candidates_by_horizon": option_counts,
                "news_notifications": self._notify_news(catalysts),
                "option_notifications": self._notify_options(option_frame),
                "options_providers": option_providers,
                "elapsed_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
                "architecture": "standalone_black_box_no_indicator_bridge",
            }
            return self._last_snapshot
        except Exception as exc:  # noqa: BLE001 - one scan failure is reported, not fatal to service
            LOGGER.exception("Black Box scan failed")
            self._last_snapshot = {
                "status": "error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }
            return self._last_snapshot
        finally:
            self._scan_lock.release()

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        stop_event = stop_event or threading.Event()
        interval = max(5, self.config.scan_minutes) * 60
        while not stop_event.is_set():
            self.scan_once()
            stop_event.wait(interval)
