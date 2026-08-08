from __future__ import annotations

import argparse
import html
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


API_TIMEOUT_SECONDS = 20
DEFAULT_STATE_PATH = Path("data/live/telegram_alert_state.json")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_text(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _stock_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in stocks
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _rvol(stock: dict[str, Any]) -> float:
    return max(
        _number(stock.get("finviz_relative_volume")),
        _number(stock.get("relative_volume")),
        _number(stock.get("rvol")),
    )


def _float_shares(stock: dict[str, Any]) -> float:
    return _number(stock.get("float_shares"), _number(stock.get("float")))


def _event_age_days(value: Any) -> int | None:
    text = str(value or "")[:10]
    try:
        event_date = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
    return max(0, (datetime.now(timezone.utc).date() - event_date).days)


def _source_strength(source: str) -> float:
    lowered = str(source or "").lower()
    if any(token in lowered for token in ("sec", "edgar", "fda", "drugs@fda", "clinicaltrials", "company ir", "investor relations")):
        return 100.0
    if any(token in lowered for token in ("reuters", "bloomberg", "wsj", "business wire", "pr newswire", "globenewswire")):
        return 82.0
    if any(token in lowered for token in ("polygon", "massive", "benzinga", "finnhub", "tiingo", "alpaca")):
        return 78.0
    if any(token in lowered for token in ("yahoo", "finviz", "stocktwits", "reddit", "x.com", "twitter")):
        return 52.0
    return 60.0


def _earlyness_score(stock: dict[str, Any], opportunity: dict[str, Any]) -> float:
    """Reward an early setup and penalize obvious chasing.

    This is a ranking aid, not a calibrated probability.
    """

    score = 100.0
    day = abs(_number(stock.get("performance_day")))
    week = abs(_number(stock.get("performance_week")))
    month = abs(_number(stock.get("performance_month")))
    gap = abs(_number(stock.get("gap_pct")))
    distance_atr = abs(_number(stock.get("distance_to_trigger_atr")))
    entry_state = str(stock.get("entry_state") or stock.get("setup_status") or "").lower()

    if day > 8:
        score -= min(28.0, (day - 8.0) * 2.3)
    if week > 20:
        score -= min(30.0, (week - 20.0) * 1.1)
    if month > 45:
        score -= min(22.0, (month - 45.0) * 0.45)
    if gap > 7:
        score -= min(18.0, (gap - 7.0) * 1.5)
    if distance_atr > 1.5:
        score -= min(25.0, (distance_atr - 1.5) * 10.0)

    if entry_state in {"early", "watch", "forming"}:
        score += 6.0
    if entry_state in {"confirmed", "breakout"}:
        score -= 4.0
    if entry_state in {"too_late", "extended"}:
        score -= 45.0

    catalyst = opportunity.get("catalyst") if isinstance(opportunity.get("catalyst"), dict) else {}
    if str(catalyst.get("reaction_state") or "").upper() == "EXTENDED_CHASING_RISK":
        score -= 45.0

    return max(0.0, min(100.0, score))


def _pre_explosion_score(opportunity: dict[str, Any], earlyness: float) -> float:
    explosion_rank = _number(opportunity.get("explosion_rank"))
    return max(0.0, min(100.0, explosion_rank * 0.72 + earlyness * 0.28))


def _dilution_risk(opportunity: dict[str, Any]) -> float:
    catalyst = opportunity.get("catalyst") if isinstance(opportunity.get("catalyst"), dict) else {}
    return _number(catalyst.get("dilution_risk"))


def _candidate_trigger(opportunity: dict[str, Any], stock: dict[str, Any]) -> float | None:
    target_map = opportunity.get("target_map") if isinstance(opportunity.get("target_map"), dict) else {}
    entry = target_map.get("entry") if isinstance(target_map.get("entry"), dict) else {}
    for value in (
        entry.get("high"),
        stock.get("entry_high"),
        stock.get("trigger"),
        stock.get("resistance20"),
        stock.get("previous_day_high"),
    ):
        numeric = _number(value, default=float("nan"))
        if math.isfinite(numeric) and numeric > 0:
            return numeric
    return None


def _candidate_invalidation(opportunity: dict[str, Any], stock: dict[str, Any]) -> float | None:
    target_map = opportunity.get("target_map") if isinstance(opportunity.get("target_map"), dict) else {}
    invalidation = target_map.get("invalidation") if isinstance(target_map.get("invalidation"), dict) else {}
    for value in (invalidation.get("price"), stock.get("invalidation"), stock.get("stop")):
        numeric = _number(value, default=float("nan"))
        if math.isfinite(numeric) and numeric > 0:
            return numeric
    return None


def _catalyst_label(opportunity: dict[str, Any]) -> str:
    catalyst = opportunity.get("catalyst") if isinstance(opportunity.get("catalyst"), dict) else {}
    for key in ("headline", "title", "summary", "event_type", "catalyst_type", "type"):
        value = str(catalyst.get(key) or "").strip()
        if value:
            return value
    why = opportunity.get("why") if isinstance(opportunity.get("why"), list) else []
    return str(why[0]) if why else "محفز متحقق داخل محرك Ω"


def _risk_label(opportunity: dict[str, Any]) -> str:
    risks = opportunity.get("risks") if isinstance(opportunity.get("risks"), list) else []
    if not risks:
        return "ما ظهر خطر حرج بالنظام حاليًا"
    return " | ".join(str(item) for item in risks[:3])


def _why_now(opportunity: dict[str, Any]) -> str:
    why = opportunity.get("why") if isinstance(opportunity.get("why"), list) else []
    if not why:
        return "اجتمعت أكثر من طبقة داخل Ω والسعر للحين بمرحلة مبكرة نسبيًا"
    return " | ".join(str(item) for item in why[:4])


@dataclass
class Candidate:
    symbol: str
    price: float
    explosion_rank: float
    earlyness: float
    pre_explosion: float
    opportunity: dict[str, Any]
    stock: dict[str, Any]
    alert_type: str = "PRE_EXPLOSION"
    alert_score: float = 0.0

    @property
    def tier(self) -> str:
        return str(self.opportunity.get("opportunity_tier") or "")

    @property
    def ranking(self) -> float:
        return self.alert_score if self.alert_score > 0 else self.pre_explosion


def select_candidates(payload: dict[str, Any]) -> list[Candidate]:
    """Existing strict PRE-EXPLOSION path."""

    min_rank = _number(os.getenv("TELEGRAM_MIN_EXPLOSION_RANK", "80"), 80.0)
    min_earlyness = _number(os.getenv("TELEGRAM_MIN_EARLYNESS", "75"), 75.0)
    max_dilution = _number(os.getenv("TELEGRAM_MAX_DILUTION_RISK", "60"), 60.0)
    max_risk_penalty = _number(os.getenv("TELEGRAM_MAX_RISK_PENALTY", "38"), 38.0)

    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    opportunities = omega.get("opportunities") if isinstance(omega.get("opportunities"), list) else []
    stocks = _stock_lookup(payload)
    selected: list[Candidate] = []

    for opportunity in opportunities:
        if not isinstance(opportunity, dict):
            continue
        symbol = str(opportunity.get("symbol") or "").upper()
        if not symbol or symbol not in stocks:
            continue
        stock = stocks[symbol]
        if str(opportunity.get("direction") or "").upper() != "UPSIDE":
            continue
        if str(opportunity.get("opportunity_tier") or "").upper() not in {"A", "A+"}:
            continue
        if not _truthy(opportunity.get("data_fresh", True)):
            continue
        if opportunity.get("no_trade_state"):
            continue

        dimensions = opportunity.get("dimensions") if isinstance(opportunity.get("dimensions"), dict) else {}
        risk_penalty = _number(dimensions.get("risk_penalty"))
        if risk_penalty > max_risk_penalty:
            continue
        if _dilution_risk(opportunity) >= max_dilution:
            continue

        rank = _number(opportunity.get("explosion_rank"))
        earlyness = _earlyness_score(stock, opportunity)
        pre_explosion = _pre_explosion_score(opportunity, earlyness)
        if rank < min_rank or earlyness < min_earlyness:
            continue

        price = _number(opportunity.get("price"), _number(stock.get("price")))
        selected.append(
            Candidate(
                symbol=symbol,
                price=price,
                explosion_rank=rank,
                earlyness=earlyness,
                pre_explosion=pre_explosion,
                opportunity=opportunity,
                stock=stock,
                alert_type="PRE_EXPLOSION",
                alert_score=pre_explosion,
            )
        )

    selected.sort(key=lambda row: (row.pre_explosion, row.explosion_rank, row.earlyness), reverse=True)
    return selected[: int(_number(os.getenv("TELEGRAM_MAX_ALERTS_PER_RUN", "3"), 3.0))]


def select_news_shock_candidates(payload: dict[str, Any]) -> list[Candidate]:
    """Strong fresh catalyst path. Options are deliberately not required."""

    min_quality = _number(os.getenv("TELEGRAM_MIN_NEWS_QUALITY", "80"), 80.0)
    min_materiality = _number(os.getenv("TELEGRAM_MIN_NEWS_MATERIALITY", "75"), 75.0)
    min_source = _number(os.getenv("TELEGRAM_MIN_NEWS_SOURCE_STRENGTH", "75"), 75.0)
    max_age_days = int(_number(os.getenv("TELEGRAM_NEWS_MAX_AGE_DAYS", "3"), 3.0))
    max_dilution = _number(os.getenv("TELEGRAM_MAX_DILUTION_RISK", "60"), 60.0)

    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    intelligence = omega.get("catalyst_intelligence") if isinstance(omega.get("catalyst_intelligence"), dict) else {}
    by_symbol = intelligence.get("by_symbol") if isinstance(intelligence.get("by_symbol"), dict) else {}
    stocks = _stock_lookup(payload)
    selected: list[Candidate] = []

    for symbol, raw_cluster in by_symbol.items():
        if not isinstance(raw_cluster, dict):
            continue
        symbol = str(symbol or "").upper()
        stock = stocks.get(symbol)
        if not stock:
            continue

        cluster = dict(raw_cluster)
        bias = str(cluster.get("directional_bias") or "").lower()
        if bias not in {"bullish", "mixed"}:
            continue
        if str(stock.get("setup_side") or "").lower() == "put" and bias == "bullish":
            continue

        quality = _number(cluster.get("catalyst_quality"))
        materiality = _number(cluster.get("materiality"))
        dilution = _number(cluster.get("dilution_risk"))
        source_strength = _source_strength(str(cluster.get("primary_source") or ""))
        age = _event_age_days(cluster.get("event_date"))
        reaction = str(cluster.get("reaction_state") or "UNKNOWN").upper()

        if quality < min_quality or materiality < min_materiality:
            continue
        if source_strength < min_source or dilution >= max_dilution:
            continue
        if age is not None and age > max_age_days:
            continue
        if reaction in {"EXTENDED_CHASING_RISK", "FAILED_REACTION"}:
            continue
        if str(stock.get("rejection_reason") or "").strip():
            continue

        pseudo_opportunity = {
            "symbol": symbol,
            "opportunity_tier": "NEWS",
            "explosion_rank": quality,
            "catalyst": cluster,
            "dimensions": {
                "participation": min(100.0, 35.0 + max(0.0, _rvol(stock) - 0.8) * 28.0),
                "supply_structure": 0.0,
                "options_structure": 0.0,
                "risk_penalty": dilution * 0.35,
            },
            "why": list(cluster.get("why_it_may_move") or [])
            + [f"Reaction {reaction}", f"RVOL {_rvol(stock):.2f}", "مسار الخبر مستقل عن توفر عقد Options"],
            "risks": list(cluster.get("why_it_may_fail") or []),
            "target_map": None,
        }
        earlyness = _earlyness_score(stock, pseudo_opportunity)
        if earlyness < 38:
            continue

        reaction_bonus = 8.0 if reaction == "REPRICING" else 5.0 if reaction == "NOT_YET_REPRICED" else 0.0
        rvol_bonus = min(8.0, max(0.0, _rvol(stock) - 1.0) * 5.0)
        alert_score = max(
            0.0,
            min(
                100.0,
                quality * 0.45
                + materiality * 0.25
                + source_strength * 0.12
                + earlyness * 0.10
                + reaction_bonus
                + rvol_bonus,
            ),
        )
        selected.append(
            Candidate(
                symbol=symbol,
                price=_number(stock.get("price")),
                explosion_rank=quality,
                earlyness=earlyness,
                pre_explosion=alert_score,
                opportunity=pseudo_opportunity,
                stock=stock,
                alert_type="NEWS_SHOCK",
                alert_score=alert_score,
            )
        )

    selected.sort(key=lambda row: (row.alert_score, row.explosion_rank, row.earlyness), reverse=True)
    return selected[: int(_number(os.getenv("TELEGRAM_MAX_ALERTS_PER_RUN", "3"), 3.0))]


def select_price_explosion_candidates(payload: dict[str, Any]) -> list[Candidate]:
    """Catch the first leg of a price/volume explosion without inventing a catalyst."""

    min_move = _number(os.getenv("TELEGRAM_MIN_PRICE_MOVE_PCT", "5"), 5.0)
    max_move = _number(os.getenv("TELEGRAM_MAX_PRICE_MOVE_PCT", "28"), 28.0)
    min_rvol = _number(os.getenv("TELEGRAM_MIN_PRICE_RVOL", "1.8"), 1.8)
    min_stock_score = _number(os.getenv("TELEGRAM_MIN_PRICE_STOCK_SCORE", "70"), 70.0)
    min_dollar_volume = _number(os.getenv("TELEGRAM_MIN_DOLLAR_VOLUME", "3000000"), 3_000_000.0)
    max_dilution = _number(os.getenv("TELEGRAM_MAX_DILUTION_RISK", "60"), 60.0)

    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    intelligence = omega.get("catalyst_intelligence") if isinstance(omega.get("catalyst_intelligence"), dict) else {}
    catalyst_by_symbol = intelligence.get("by_symbol") if isinstance(intelligence.get("by_symbol"), dict) else {}

    selected: list[Candidate] = []
    for symbol, stock in _stock_lookup(payload).items():
        day = _number(stock.get("performance_day"))
        week = _number(stock.get("performance_week"))
        month = _number(stock.get("performance_month"))
        gap = abs(_number(stock.get("gap_pct")))
        rvol = _rvol(stock)
        stock_score = _number(stock.get("score"))
        dollar_volume = _number(stock.get("avg_dollar_volume"))
        distance = abs(_number(stock.get("distance_to_trigger_atr")))
        entry_state = str(stock.get("entry_state") or stock.get("setup_status") or "").lower()
        side = str(stock.get("setup_side") or "").lower()
        breakout = _truthy(stock.get("breakout"))

        if day < min_move or day > max_move:
            continue
        if rvol < min_rvol or dollar_volume < min_dollar_volume:
            continue
        if side == "put":
            continue
        if stock_score < min_stock_score and not breakout and entry_state not in {"early", "confirmed", "breakout"}:
            continue
        if gap >= 12 or distance > 2.5:
            continue
        if week > 55 or month > 95:
            continue
        if entry_state in {"too_late", "extended"}:
            continue
        if str(stock.get("rejection_reason") or "").strip():
            continue

        cluster = catalyst_by_symbol.get(symbol)
        if isinstance(cluster, dict):
            if _number(cluster.get("dilution_risk")) >= max_dilution:
                continue
            if str(cluster.get("reaction_state") or "").upper() == "EXTENDED_CHASING_RISK":
                continue

        pseudo_opportunity = {
            "symbol": symbol,
            "opportunity_tier": "MOMENTUM",
            "explosion_rank": 0.0,
            "catalyst": cluster if isinstance(cluster, dict) else {},
            "dimensions": {
                "participation": min(100.0, 35.0 + max(0.0, rvol - 0.8) * 28.0),
                "supply_structure": 0.0,
                "options_structure": 0.0,
                "risk_penalty": 0.0,
            },
            "why": [
                f"السعر اليوم +{day:.1f}%",
                f"RVOL {rvol:.2f}",
                f"20D avg dollar volume ${dollar_volume:,.0f}",
                "التنبيه مبني على السعر والحجم، مو على خبر مفترض",
            ],
            "risks": [
                "الحركة ممكن تفشل بسرعة لو اختفى الحجم",
                "ما نعتبر وجود خبر إلا إذا كان موثق داخل Catalyst Intelligence",
            ],
            "target_map": None,
        }
        earlyness = _earlyness_score(stock, pseudo_opportunity)
        if earlyness < 42:
            continue

        move_component = min(100.0, day / max(max_move, 1.0) * 100.0)
        rvol_component = min(100.0, rvol / 4.0 * 100.0)
        liquidity_component = min(100.0, math.log10(max(dollar_volume, 1.0)) / 8.0 * 100.0)
        alert_score = max(
            0.0,
            min(
                100.0,
                move_component * 0.30
                + rvol_component * 0.30
                + max(stock_score, 55.0) * 0.20
                + earlyness * 0.15
                + liquidity_component * 0.05,
            ),
        )
        pseudo_opportunity["explosion_rank"] = alert_score

        selected.append(
            Candidate(
                symbol=symbol,
                price=_number(stock.get("price")),
                explosion_rank=alert_score,
                earlyness=earlyness,
                pre_explosion=alert_score,
                opportunity=pseudo_opportunity,
                stock=stock,
                alert_type="PRICE_EXPLOSION",
                alert_score=alert_score,
            )
        )

    selected.sort(key=lambda row: (row.alert_score, row.earlyness, _rvol(row.stock)), reverse=True)
    return selected[: int(_number(os.getenv("TELEGRAM_MAX_ALERTS_PER_RUN", "3"), 3.0))]


def select_alert_candidates(payload: dict[str, Any]) -> list[Candidate]:
    """Merge all paths and emit at most one explanation per symbol per run."""

    candidates = select_news_shock_candidates(payload) + select_candidates(payload) + select_price_explosion_candidates(payload)
    priority = {"NEWS_SHOCK": 3, "PRE_EXPLOSION": 2, "PRICE_EXPLOSION": 1}
    best_by_symbol: dict[str, Candidate] = {}

    for candidate in candidates:
        existing = best_by_symbol.get(candidate.symbol)
        if existing is None:
            best_by_symbol[candidate.symbol] = candidate
            continue
        current_key = (priority.get(candidate.alert_type, 0), candidate.ranking)
        existing_key = (priority.get(existing.alert_type, 0), existing.ranking)
        if current_key > existing_key:
            best_by_symbol[candidate.symbol] = candidate

    merged = list(best_by_symbol.values())
    merged.sort(key=lambda row: (row.ranking, priority.get(row.alert_type, 0), row.earlyness), reverse=True)
    maximum = int(_number(os.getenv("TELEGRAM_MAX_ALERTS_PER_RUN", "3"), 3.0))
    return merged[:maximum]


def _telegram_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _resolve_chat_id(token: str) -> str:
    configured = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if configured:
        return configured

    response = requests.get(_telegram_url(token, "getUpdates"), timeout=API_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram getUpdates رجع خطأ")

    results = payload.get("result") if isinstance(payload.get("result"), list) else []
    for update in reversed(results):
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message") or update.get("channel_post")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        chat_id = chat.get("id")
        if chat_id is not None:
            return str(chat_id)
    raise RuntimeError("ما لقيت Chat ID. أرسل /start أو أي رسالة للبوت وبعدين شغّل الفحص مرة ثانية")


def _send_message(token: str, chat_id: str, text: str) -> None:
    response = requests.post(
        _telegram_url(token, "sendMessage"),
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        timeout=API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram sendMessage رجع خطأ")


def _format_price(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "غير متوفر"
    return f"${value:,.2f}"


def _source_link(cluster: dict[str, Any]) -> str:
    source = _safe_text(cluster.get("primary_source") or "غير متوفر", 150)
    url = str(cluster.get("primary_url") or "").strip()
    if url.startswith(("https://", "http://")):
        safe_url = html.escape(url, quote=True)
        return f'<a href="{safe_url}">{source}</a>'
    return source


def _pre_explosion_message(candidate: Candidate) -> str:
    trigger = _candidate_trigger(candidate.opportunity, candidate.stock)
    invalidation = _candidate_invalidation(candidate.opportunity, candidate.stock)
    catalyst = _catalyst_label(candidate.opportunity)
    why = _why_now(candidate.opportunity)
    risks = _risk_label(candidate.opportunity)
    dimensions = candidate.opportunity.get("dimensions") if isinstance(candidate.opportunity.get("dimensions"), dict) else {}
    participation = _number(dimensions.get("participation"))
    supply = _number(dimensions.get("supply_structure"))
    options_score = _number(dimensions.get("options_structure"))

    return (
        "🚨 <b>BLACK BOX Ω — PRE-EXPLOSION</b>\n\n"
        f"<b>{_safe_text(candidate.symbol)}</b> — {_format_price(candidate.price)}\n"
        f"الرتبة: <b>{_safe_text(candidate.tier)}</b>\n"
        f"Pre-Explosion: <b>{candidate.pre_explosion:.0f}/100</b> <i>(ترتيب، مو احتمال)</i>\n"
        f"Explosion Rank: <b>{candidate.explosion_rank:.0f}/100</b>\n"
        f"Earlyness: <b>{candidate.earlyness:.0f}/100</b>\n\n"
        f"📌 <b>ليش ظهر الحين؟</b>\n{_safe_text(why, 900)}\n\n"
        f"⚡ <b>المحفز</b>\n{_safe_text(catalyst, 700)}\n\n"
        f"📊 الطلب/الحجم: <b>{participation:.0f}/100</b>\n"
        f"🧩 العرض/Float: <b>{supply:.0f}/100</b>\n"
        f"🟣 الخيارات: <b>{options_score:.0f}/100</b>\n\n"
        f"🎯 نقطة المراقبة/التفعيل: <b>{_format_price(trigger)}</b>\n"
        f"🛑 يبطل الفكرة تقريبًا عند: <b>{_format_price(invalidation)}</b>\n\n"
        f"⚠️ <b>أهم المخاطر</b>\n{_safe_text(risks, 850)}\n\n"
        "الحالة: <b>WATCH — للحين مو مطاردة</b>"
    )


def _news_shock_message(candidate: Candidate) -> str:
    cluster = candidate.opportunity.get("catalyst") if isinstance(candidate.opportunity.get("catalyst"), dict) else {}
    trigger = _candidate_trigger(candidate.opportunity, candidate.stock)
    invalidation = _candidate_invalidation(candidate.opportunity, candidate.stock)
    quality = _number(cluster.get("catalyst_quality"))
    materiality = _number(cluster.get("materiality"))
    dilution = _number(cluster.get("dilution_risk"))
    reaction = str(cluster.get("reaction_state") or "UNKNOWN")
    day = _number(candidate.stock.get("performance_day"))
    rvol = _rvol(candidate.stock)
    headline = str(cluster.get("headline") or _catalyst_label(candidate.opportunity))
    risks = " | ".join(str(item) for item in (cluster.get("why_it_may_fail") or [])[:3])
    if not risks:
        risks = "لا يزال لازم السعر والسيولة يؤكدون الخبر"

    return (
        "📰⚡ <b>BLACK BOX Ω — NEWS SHOCK</b>\n\n"
        f"<b>{_safe_text(candidate.symbol)}</b> — {_format_price(candidate.price)}\n"
        f"News Signal: <b>{candidate.alert_score:.0f}/100</b> <i>(ترتيب، مو احتمال)</i>\n"
        f"Catalyst Quality: <b>{quality:.0f}/100</b>\n"
        f"Materiality: <b>{materiality:.0f}/100</b>\n\n"
        f"🧨 <b>الخبر</b>\n{_safe_text(headline, 900)}\n\n"
        f"🔎 المصدر: {_source_link(cluster)}\n"
        f"📍 حالة إعادة التسعير: <b>{_safe_text(reaction)}</b>\n"
        f"📈 حركة اليوم: <b>{day:+.1f}%</b>\n"
        f"📊 RVOL: <b>{rvol:.2f}</b>\n"
        f"💧 Dilution Risk: <b>{dilution:.0f}/100</b>\n\n"
        f"🎯 نقطة المراقبة/التفعيل: <b>{_format_price(trigger)}</b>\n"
        f"🛑 يبطل الفكرة تقريبًا عند: <b>{_format_price(invalidation)}</b>\n\n"
        f"⚠️ <b>أهم المخاطر</b>\n{_safe_text(risks, 900)}\n\n"
        "الحالة: <b>خبر قوي ومتحقق — هذا المسار ما يشترط Options</b>"
    )


def _price_explosion_message(candidate: Candidate) -> str:
    stock = candidate.stock
    trigger = _candidate_trigger(candidate.opportunity, stock)
    invalidation = _candidate_invalidation(candidate.opportunity, stock)
    day = _number(stock.get("performance_day"))
    week = _number(stock.get("performance_week"))
    gap = _number(stock.get("gap_pct"))
    rvol = _rvol(stock)
    dollar_volume = _number(stock.get("avg_dollar_volume"))
    float_shares = _float_shares(stock)
    score = _number(stock.get("score"))
    float_text = f"{float_shares:,.0f}" if float_shares > 0 else "غير متوفر"

    return (
        "🔥 <b>BLACK BOX Ω — PRICE EXPLOSION EARLY</b>\n\n"
        f"<b>{_safe_text(candidate.symbol)}</b> — {_format_price(candidate.price)}\n"
        f"Explosion Signal: <b>{candidate.alert_score:.0f}/100</b> <i>(ترتيب، مو احتمال)</i>\n"
        f"Earlyness: <b>{candidate.earlyness:.0f}/100</b>\n\n"
        f"📈 حركة اليوم: <b>{day:+.1f}%</b>\n"
        f"📅 حركة الأسبوع: <b>{week:+.1f}%</b>\n"
        f"↗️ Gap: <b>{gap:+.1f}%</b>\n"
        f"📊 RVOL: <b>{rvol:.2f}</b>\n"
        f"💵 20D Avg Dollar Volume: <b>${dollar_volume:,.0f}</b>\n"
        f"🧩 Float: <b>{float_text}</b>\n"
        f"📐 Stock Setup Score: <b>{score:.0f}/100</b>\n\n"
        f"🎯 نقطة المراقبة/التفعيل: <b>{_format_price(trigger)}</b>\n"
        f"🛑 يبطل الفكرة تقريبًا عند: <b>{_format_price(invalidation)}</b>\n\n"
        "⚠️ <b>مهم</b>\n"
        "هذا التنبيه مبني على انفجار السعر + الحجم. ما أفترض وجود خبر، ولو اختفى الحجم بسرعة فالإشارة تضعف.\n\n"
        "الحالة: <b>الحركة بدأت — لكن فلتر المطاردة للحين يعتبرها قابلة للمراقبة</b>"
    )


def _candidate_message(candidate: Candidate) -> str:
    if candidate.alert_type == "NEWS_SHOCK":
        return _news_shock_message(candidate)
    if candidate.alert_type == "PRICE_EXPLOSION":
        return _price_explosion_message(candidate)
    return _pre_explosion_message(candidate)


def _fingerprint(candidate: Candidate) -> str:
    trigger = _candidate_trigger(candidate.opportunity, candidate.stock)
    catalyst = _catalyst_label(candidate.opportunity)
    day = _number(candidate.stock.get("performance_day"))
    rvol = _rvol(candidate.stock)
    return "|".join(
        [
            candidate.alert_type,
            candidate.symbol,
            candidate.tier,
            f"{round(candidate.explosion_rank / 5) * 5:.0f}",
            f"{round(candidate.alert_score / 5) * 5:.0f}",
            f"{trigger:.2f}" if trigger is not None else "none",
            f"day:{day:.1f}",
            f"rvol:{rvol:.1f}",
            catalyst[:120],
        ]
    )


def _state_key(candidate: Candidate) -> str:
    return f"{candidate.alert_type}:{candidate.symbol}"


def _should_send(candidate: Candidate, previous: dict[str, Any]) -> bool:
    key = _state_key(candidate)
    entry = previous.get(key) if isinstance(previous.get(key), dict) else {}
    if not entry and candidate.alert_type == "PRE_EXPLOSION":
        entry = previous.get(candidate.symbol) if isinstance(previous.get(candidate.symbol), dict) else {}
    if not entry:
        return True
    current_fingerprint = _fingerprint(candidate)
    if str(entry.get("fingerprint") or "") != current_fingerprint:
        return True
    last_rank = _number(entry.get("explosion_rank"))
    last_earlyness = _number(entry.get("earlyness"))
    last_alert_score = _number(entry.get("alert_score"), _number(entry.get("pre_explosion")))
    if candidate.explosion_rank >= last_rank + 7:
        return True
    if candidate.earlyness >= last_earlyness + 10:
        return True
    if candidate.alert_score >= last_alert_score + 7:
        return True
    return False


def _update_state(state: dict[str, Any], candidate: Candidate) -> None:
    sent = state.setdefault("sent", {})
    sent[_state_key(candidate)] = {
        "alert_type": candidate.alert_type,
        "symbol": candidate.symbol,
        "fingerprint": _fingerprint(candidate),
        "explosion_rank": round(candidate.explosion_rank, 1),
        "earlyness": round(candidate.earlyness, 1),
        "pre_explosion": round(candidate.pre_explosion, 1),
        "alert_score": round(candidate.alert_score, 1),
        "sent_at": _utc_now(),
    }


def notify(payload_path: Path, state_path: Path = DEFAULT_STATE_PATH) -> int:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print("Telegram: TELEGRAM_BOT_TOKEN مو مضبوط؛ تخطيت الإرسال.")
        return 0

    payload = _load_json(payload_path, {})
    if not isinstance(payload, dict) or not payload:
        print("Telegram: ملف نتائج Ω فاضي أو غير صالح؛ ما أرسلت شيء.")
        return 0

    chat_id = _resolve_chat_id(token)
    state = _load_json(state_path, {"connected_sent": False, "sent": {}})
    if not isinstance(state, dict):
        state = {"connected_sent": False, "sent": {}}

    if not state.get("connected_sent"):
        _send_message(
            token,
            chat_id,
            "✅ <b>BLACK BOX Ω CONNECTED</b>\n\nتم ربط المحرك بتيليجرام. التنبيهات تشمل الآن: PRE-EXPLOSION + NEWS SHOCK + PRICE EXPLOSION EARLY.",
        )
        state["connected_sent"] = True
        state["connected_at"] = _utc_now()

    candidates = select_alert_candidates(payload)
    sent_map = state.setdefault("sent", {})
    sent_count = 0
    for candidate in candidates:
        if not _should_send(candidate, sent_map):
            continue
        _send_message(token, chat_id, _candidate_message(candidate))
        _update_state(state, candidate)
        sent_count += 1

    state["last_run_at"] = _utc_now()
    state["last_candidates"] = [
        {"symbol": candidate.symbol, "type": candidate.alert_type, "score": round(candidate.ranking, 1)}
        for candidate in candidates
    ]
    state["last_sent_count"] = sent_count
    _write_json_atomic(state_path, state)
    print(f"Telegram: candidates={len(candidates)} sent={sent_count} types={[candidate.alert_type for candidate in candidates]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BLACK BOX Ω Telegram notifier")
    parser.add_argument("--payload", default="public/data/latest.json")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return notify(Path(args.payload), Path(args.state))
    except requests.RequestException as exc:
        print(f"Telegram network error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Telegram notifier error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
