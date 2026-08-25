from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
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
    enabled: bool = (os.getenv("BLACK_BOX_BOT_ENABLED", "true").lower() in {"1", "true", "yes", "on"})
    scan_minutes: int = int(os.getenv("BLACK_BOX_SCAN_MINUTES", "15"))
    top_stocks: int = int(os.getenv("BLACK_BOX_TOP_STOCKS", "20"))
    top_options: int = int(os.getenv("BLACK_BOX_TOP_OPTIONS", "15"))
    universe_path: str = os.getenv("BLACK_BOX_UNIVERSE", "data/universe.txt")
    telegram_token: str | None = os.getenv("TELEGRAM_BOT_TOKEN") or None
    telegram_chat_id: str | None = os.getenv("TELEGRAM_CHAT_ID") or None
    webhook_secret: str | None = os.getenv("SNIPER_WEBHOOK_SECRET") or None
    state_path: Path = Path(os.getenv("BLACK_BOX_BOT_STATE", "data/live/black_box_bot_state.json"))
    notify_sniper_score: int = int(os.getenv("SNIPER_NOTIFY_SCORE", "80"))


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
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        response = self.session.post(
            url,
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
    """Small durable dedupe ledger for scanner/news/webhook notifications."""

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
        except Exception as exc:
            LOGGER.warning("Could not load bot ledger %s: %s", self.path, exc)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"seen": self._seen}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
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
    """Bridge SNIPER TradingView alerts with options flow and company catalysts.

    It never submits broker orders. Its purpose is monitoring, evidence aggregation,
    ranking and notification. TradingView remains the source of SNIPER chart signals;
    the server enriches those signals with the radar's stock/options/catalyst context.
    """

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
        return list(dict.fromkeys(str(s).upper().strip() for s in symbols if str(s).strip()))

    @staticmethod
    def _safe(value: Any, default: str = "-") -> str:
        if value is None:
            return default
        try:
            if pd.isna(value):
                return default
        except Exception:
            pass
        return str(value)

    def _notify_news(self, catalysts: pd.DataFrame) -> int:
        sent = 0
        if catalysts.empty:
            return sent
        rows = catalysts.sort_values("score", ascending=False).head(30)
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
            message = (
                "📰 بلاك بوكس | خبر جوهري\n"
                f"السهم: {identity['symbol']}\n"
                f"التقييم: {direction} ({score:.0f})\n"
                f"الخبر: {identity['headline']}\n"
                f"الفئة: {self._safe(row.get('category'))}\n"
                f"المصدر: {identity['source']}\n"
                f"الدليل: {self._safe(row.get('evidence'))}"
            )
            self.notifier.send(message)
            sent += 1
        return sent

    def _notify_options(self, frame: pd.DataFrame) -> int:
        sent = 0
        if frame.empty:
            return sent
        candidates = frame.copy()
        if "new_setup_candidate" in candidates:
            candidates = candidates[candidates["new_setup_candidate"] == True]  # noqa: E712
        candidates = candidates.sort_values("score", ascending=False).head(self.config.top_options * 2)
        for _, row in candidates.iterrows():
            identity = {
                "contract": self._safe(row.get("contract_symbol")),
                "score": round(float(row.get("score", 0) or 0), 1),
                "volume": int(float(row.get("volume", 0) or 0)),
                "oi": int(float(row.get("open_interest", 0) or 0)),
            }
            if not identity["contract"] or identity["contract"] == "-":
                continue
            if not self.ledger.first_time("option", identity):
                continue
            option_type = self._safe(row.get("option_type")).upper()
            side_ar = "كول" if option_type == "CALL" else "بوت" if option_type == "PUT" else option_type
            message = (
                "🎯 بلاك بوكس | رصد عقد\n"
                f"السهم: {self._safe(row.get('symbol'))}\n"
                f"العقد: {side_ar} | تنفيذ {self._safe(row.get('strike'))} | انتهاء {self._safe(row.get('expiration'))[:10]}\n"
                f"الجودة: {identity['score']}/100 | {self._safe(row.get('rating'))}\n"
                f"الحجم/OI: {self._safe(row.get('vol_oi'))}\n"
                f"الحجم: {identity['volume']:,} | OI: {identity['oi']:,}\n"
                f"دلتا: {self._safe(row.get('delta'))} | IV: {self._safe(row.get('iv'))}\n"
                f"دخول تقريبي: {self._safe(row.get('entry_price'))}\n"
                f"هدف 1: {self._safe(row.get('target_1'))} | هدف 2: {self._safe(row.get('target_2'))}\n"
                f"إلغاء: {self._safe(row.get('stop_price'))}\n"
                f"المحفز: {self._safe(row.get('catalyst'))}\n"
                f"البيانات: {self._safe(row.get('source'))} — {self._safe(row.get('freshness_label'))}\n"
                "تنبيه رصد وليس أمر تنفيذ."
            )
            self.notifier.send(message)
            sent += 1
        return sent

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
            option_result = OptionsRadar(self.settings).scan(
                option_symbols,
                top=self.config.top_options,
                output_csv="results/options_latest.csv",
                catalysts=catalysts,
            )
            news_sent = self._notify_news(catalysts)
            option_sent = self._notify_options(option_result.opportunities)
            self._last_snapshot = {
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbols": len(symbols),
                "market_regime": stock_result.regime,
                "stock_candidates": int(len(stock_result.opportunities)),
                "option_candidates": int(len(option_result.opportunities)),
                "news_notifications": news_sent,
                "option_notifications": option_sent,
                "options_provider": option_result.provider,
                "elapsed_seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 2),
            }
            return self._last_snapshot
        except Exception as exc:
            LOGGER.exception("Black Box scan failed")
            self._last_snapshot = {
                "status": "error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }
            return self._last_snapshot
        finally:
            self._scan_lock.release()

    def handle_sniper(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and relay one SNIPER webhook event from TradingView."""
        event = str(payload.get("event", "")).strip().lower()
        direction = str(payload.get("direction", "")).strip().lower()
        symbol = str(payload.get("symbol", "")).strip().upper()
        score = int(float(payload.get("score", 0) or 0))
        allowed_events = {"signal", "call", "put", "setup", "invalidation", "target"}
        if event not in allowed_events:
            raise ValueError(f"unsupported event: {event!r}")
        if not symbol:
            raise ValueError("symbol is required")
        if direction not in {"call", "put", "bull", "bear", "none", ""}:
            raise ValueError(f"unsupported direction: {direction!r}")

        fingerprint = {
            "event": event,
            "direction": direction,
            "symbol": symbol,
            "time": payload.get("time"),
            "entry": payload.get("entry"),
            "score": score,
        }
        fresh = self.ledger.first_time("sniper", fingerprint)
        if not fresh:
            return {"status": "duplicate", "accepted": True}

        side = "كول" if direction in {"call", "bull"} else "بوت" if direction in {"put", "bear"} else "-"
        should_notify = event in {"invalidation", "target"} or score >= self.config.notify_sniper_score
        if should_notify:
            message = (
                "🎯 سنايبر × بلاك بوكس\n"
                f"السهم/المؤشر: {symbol}\n"
                f"الحدث: {event}\n"
                f"الاتجاه: {side}\n"
                f"الجودة: {score}/100\n"
                f"الفريم: {self._safe(payload.get('timeframe'))}\n"
                f"الدخول: {self._safe(payload.get('entry'))}\n"
                f"الإلغاء: {self._safe(payload.get('stop'))}\n"
                f"الهدف 1: {self._safe(payload.get('target1'))}\n"
                f"الهدف 2: {self._safe(payload.get('target2'))}\n"
                f"الهدف 3: {self._safe(payload.get('target3'))}\n"
                f"المحرك: {self._safe(payload.get('engine'))}\n"
                f"السبب: {self._safe(payload.get('reason'))}"
            )
            self.notifier.send(message)
        return {"status": "ok", "accepted": True, "notified": should_notify}

    def run_forever(self, stop_event: threading.Event | None = None) -> None:
        stop_event = stop_event or threading.Event()
        interval = max(5, self.config.scan_minutes) * 60
        while not stop_event.is_set():
            self.scan_once()
            stop_event.wait(interval)
