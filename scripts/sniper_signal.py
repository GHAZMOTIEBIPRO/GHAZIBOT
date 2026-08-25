from __future__ import annotations

import html
import math
import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1000:
        return f"{value:,.2f}"
    if abs(value) >= 100:
        return f"{value:.2f}"
    return f"{value:.2f}" if abs(value) >= 1 else f"{value:.3f}"


def _normalize_direction(value: Any) -> str:
    raw = str(value or "").strip().upper()
    mapping = {
        "CALL": "CALL",
        "كول": "CALL",
        "LONG": "CALL",
        "BUY": "CALL",
        "PUT": "PUT",
        "بوت": "PUT",
        "SHORT": "PUT",
        "SELL": "PUT",
    }
    return mapping.get(raw, "")


def _normalize_horizon(value: Any) -> str:
    raw = str(value or "").strip()
    low = raw.lower()
    if raw in {"يومي", "أسبوعي", "شهري", "مخصص"}:
        return raw
    if low in {"daily", "day", "0dte", "1dte"}:
        return "يومي"
    if low in {"weekly", "week"}:
        return "أسبوعي"
    if low in {"monthly", "month", "swing"}:
        return "شهري"
    return "مخصص"


def _ticker_root(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    root = raw.rsplit(":", 1)[-1].strip()
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-^"
    root = "".join(ch for ch in root if ch in allowed)
    return root[:24]


@dataclass(frozen=True)
class SniperEvent:
    symbol: str
    ticker_id: str
    direction: str
    score: float
    grade: str
    horizon: str
    timeframe: str
    entry: float | None
    stop: float | None
    target_1: float | None
    target_2: float | None
    reward_risk: float | None
    engine: str
    regime: str
    trigger: float | None
    event_time_ms: int | None
    schema: str = "sniper.v1"

    @property
    def side_ar(self) -> str:
        return "كول" if self.direction == "CALL" else "بوت"

    @property
    def side_emoji(self) -> str:
        return "🟢" if self.direction == "CALL" else "🔴"


def parse_sniper_event(payload: dict[str, Any], *, now: datetime | None = None) -> SniperEvent:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    schema = str(payload.get("schema") or "").strip()
    source = str(payload.get("source") or payload.get("indicator") or "").strip().lower()
    if schema not in {"sniper.v1", "sniper.v2"}:
        raise ValueError("unsupported sniper schema")
    if source not in {"سنايبر", "sniper"}:
        raise ValueError("unexpected indicator source")

    ticker_id = str(payload.get("ticker_id") or payload.get("symbol") or "").strip().upper()
    symbol = _ticker_root(payload.get("symbol") or ticker_id)
    if not symbol:
        raise ValueError("missing symbol")
    direction = _normalize_direction(payload.get("direction"))
    if direction not in {"CALL", "PUT"}:
        raise ValueError("direction must be CALL or PUT")
    score = _finite(payload.get("score"))
    if score is None or not 0 <= score <= 100:
        raise ValueError("score must be between 0 and 100")

    event_time_raw = payload.get("event_time_ms") or payload.get("time_close_ms") or payload.get("time_ms")
    event_time_ms: int | None = None
    try:
        if event_time_raw is not None:
            event_time_ms = int(float(event_time_raw))
    except (TypeError, ValueError, OverflowError):
        event_time_ms = None
    if event_time_ms is not None:
        current = now or datetime.now(timezone.utc)
        event_time = datetime.fromtimestamp(event_time_ms / 1000.0, tz=timezone.utc)
        max_age = max(60, int(os.getenv("SNIPER_MAX_EVENT_AGE_SECONDS", "900")))
        age = (current - event_time).total_seconds()
        if age > max_age:
            raise ValueError("stale sniper event")
        if age < -180:
            raise ValueError("sniper event timestamp is too far in the future")

    return SniperEvent(
        symbol=symbol,
        ticker_id=ticker_id or symbol,
        direction=direction,
        score=score,
        grade=str(payload.get("grade") or "-").strip()[:16] or "-",
        horizon=_normalize_horizon(payload.get("horizon") or payload.get("contract_mode")),
        timeframe=str(payload.get("timeframe") or "-").strip()[:16] or "-",
        entry=_finite(payload.get("entry")),
        stop=_finite(payload.get("stop") or payload.get("invalidation")),
        target_1=_finite(payload.get("target_1") or payload.get("t1")),
        target_2=_finite(payload.get("target_2") or payload.get("t2")),
        reward_risk=_finite(payload.get("reward_risk") or payload.get("rr")),
        engine=str(payload.get("engine") or "-").strip()[:48] or "-",
        regime=str(payload.get("regime") or "-").strip()[:48] or "-",
        trigger=_finite(payload.get("trigger")),
        event_time_ms=event_time_ms,
        schema=schema,
    )


def format_sniper_message(event: SniperEvent) -> str:
    rr = "-" if event.reward_risk is None else f"{event.reward_risk:.2f}"
    lines = [
        f"{event.side_emoji} <b>سنايبر | {_safe(event.symbol)} | {event.side_ar}</b>",
        f"🎯 الجودة <b>{event.score:.0f}/100 {_safe(event.grade, 16)}</b> | الأفق <b>{_safe(event.horizon, 16)}</b> | الفريم <b>{_safe(event.timeframe, 16)}</b>",
        f"📍 دخول <b>{_fmt_price(event.entry)}</b> | إلغاء <b>{_fmt_price(event.stop)}</b>",
        f"🏁 هدف 1 <b>{_fmt_price(event.target_1)}</b> | هدف 2 <b>{_fmt_price(event.target_2)}</b> | ع/م <b>{rr}</b>",
    ]
    if event.trigger is not None:
        lines.append(f"⚡ التفعيل <b>{_fmt_price(event.trigger)}</b>")
    context = []
    if event.engine and event.engine != "-":
        context.append(f"المحرك: {_safe(event.engine, 48)}")
    if event.regime and event.regime != "-":
        context.append(f"حالة السوق: {_safe(event.regime, 48)}")
    if context:
        lines.append("🧠 " + " | ".join(context))
    lines.append("🔎 <i>يتم فحص العقد والخبر في الخلفية؛ الإشارة مبنية على حركة الأصل الأساسي.</i>")
    return "\n".join(lines)


def _horizon_dte(horizon: str) -> tuple[int, int]:
    if horizon == "يومي":
        return 0, 2
    if horizon == "أسبوعي":
        return 3, 10
    if horizon == "شهري":
        return 14, 45
    return 7, 45


def enrich_sniper_message(event: SniperEvent, base_text: str) -> str:
    from options_radar.catalysts import CatalystScanner
    from options_radar.scanner import OptionsRadar
    from options_radar.settings import Settings

    settings = Settings()
    min_dte, max_dte = _horizon_dte(event.horizon)
    tuned = replace(settings, min_dte=min_dte, max_dte=max_dte)
    tuned.validate()
    catalyst_frame = CatalystScanner(tuned).scan([event.symbol], lookback_days=3)
    option_result = OptionsRadar(tuned).scan([event.symbol], top=5, catalysts=catalyst_frame)

    additions: list[str] = []
    side_frame = option_result.top_calls if event.direction == "CALL" else option_result.top_puts
    if side_frame is not None and not side_frame.empty:
        row = side_frame.iloc[0]
        expiration = str(row.get("expiration") or "")[:10]
        strike = _finite(row.get("strike"))
        bid = _finite(row.get("bid"))
        ask = _finite(row.get("ask"))
        score = _finite(row.get("score"))
        vol_oi = _finite(row.get("vol_to_oi_ratio") or row.get("vol_oi"))
        delta = _finite(row.get("delta"))
        spread = _finite(row.get("spread_pct"))
        source = _safe(row.get("source") or option_result.provider, 80)
        freshness = _safe(row.get("freshness_label") or "غير محدد", 80)
        contract_symbol = _safe(row.get("contract_symbol") or "", 80)
        strike_text = "-" if strike is None else f"{strike:g}"
        lines = ["", "📑 <b>رصد العقد المتوافق</b>", f"العقد: <b>{strike_text}{'C' if event.direction == 'CALL' else 'P'} • {expiration}</b>"]
        if contract_symbol:
            lines.append(f"OCC: <code>{contract_symbol}</code>")
        if bid is not None or ask is not None:
            lines.append(f"سعر B/A: <b>{_fmt_price(bid)} / {_fmt_price(ask)}</b>")
        metrics: list[str] = []
        if score is not None:
            metrics.append(f"تقييم {score:.0f}/100")
        if vol_oi is not None:
            metrics.append(f"V/OI {vol_oi:.2f}×")
        if delta is not None:
            metrics.append(f"Δ {delta:+.2f}")
        if spread is not None:
            metrics.append(f"سبريد {spread * 100:.1f}%")
        if metrics:
            lines.append(" | ".join(metrics))
        lines.append(f"المصدر: {source} | الحداثة: {freshness}")
        lines.append("<i>بيانات العقد سياق تأكيدي؛ جودة التنفيذ تعتمد على نوع تغذية السوق المتاحة.</i>")
        additions.append("\n".join(lines))

    if catalyst_frame is not None and not catalyst_frame.empty:
        ranked = catalyst_frame.copy()
        ranked["abs_score"] = ranked["score"].abs()
        news = ranked.sort_values(["abs_score", "event_date"], ascending=[False, False]).iloc[0]
        nscore = _finite(news.get("score")) or 0.0
        icon = "🟢" if nscore > 0 else "🔴" if nscore < 0 else "🟡"
        additions.append("\n".join(["", f"{icon} <b>خبر/محفز مرتبط</b>", f"{_safe(news.get('headline'), 360)}", f"التصنيف: {_safe(news.get('category'), 120)} | الأثر الخام: <b>{nscore:+.0f}</b>", f"المصدر: {_safe(news.get('source'), 100)} | التاريخ: {_safe(news.get('event_date'), 20)}"]))
    return base_text + "\n".join(additions) if additions else base_text
