from __future__ import annotations

import argparse
import html
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

API_TIMEOUT_SECONDS = 20
DEFAULT_STATE_PATH = Path("data/live/asymmetric_alert_state.json")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _pct(value: Any) -> float:
    number = _number(value)
    if 0 < number <= 1:
        number *= 100.0
    return number


def _safe(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _telegram_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _resolve_chat_id(token: str) -> str:
    configured = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if configured:
        return configured
    response = requests.get(_telegram_url(token, "getUpdates"), timeout=API_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError("Telegram getUpdates failed")
    for update in reversed(body.get("result") or []):
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message") or update.get("channel_post")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        if chat.get("id") is not None:
            return str(chat["id"])
    raise RuntimeError("Telegram Chat ID unavailable; send any message to the bot once")


def _send(token: str, chat_id: str, text: str) -> None:
    response = requests.post(
        _telegram_url(token, "sendMessage"),
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"},
        timeout=API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise RuntimeError("Telegram sendMessage failed")


def _first_number(row: dict[str, Any], keys: tuple[str, ...]) -> float:
    for key in keys:
        if row.get(key) is None:
            continue
        value = _number(row.get(key), float("nan"))
        if math.isfinite(value):
            return value
    return 0.0


def _float_shares(stock: dict[str, Any]) -> float:
    return _first_number(stock, ("public_float_shares", "float_shares", "public_float", "float"))


def _shares_outstanding(stock: dict[str, Any]) -> float:
    return _first_number(stock, ("shares_outstanding", "outstanding_shares", "shares"))


def _insider_pct(stock: dict[str, Any]) -> float:
    for key in ("insider_ownership_pct", "insider_ownership", "insider_owned_pct", "insider_pct"):
        if stock.get(key) is not None:
            return _pct(stock.get(key))
    return 0.0


def _rvol(stock: dict[str, Any]) -> float:
    return max(_number(stock.get("finviz_relative_volume")), _number(stock.get("relative_volume")))


def _day_move(stock: dict[str, Any]) -> float:
    return _first_number(stock, ("performance_day", "change_pct", "price_change_pct", "day_change_pct", "gap_pct"))


def _week_move(stock: dict[str, Any]) -> float:
    return _first_number(stock, ("performance_week", "week_change_pct", "change_5d_pct"))


def _social_score(stock: dict[str, Any]) -> float:
    direct = _number(stock.get("social_score"))
    evidence = stock.get("external_evidence") if isinstance(stock.get("external_evidence"), dict) else {}
    return max(direct, _number(evidence.get("social_score")))


def _catalyst_maps(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    intelligence = omega.get("catalyst_intelligence") if isinstance(omega.get("catalyst_intelligence"), dict) else {}
    by_symbol = intelligence.get("by_symbol") if isinstance(intelligence.get("by_symbol"), dict) else {}
    return {str(k).upper(): v for k, v in by_symbol.items() if isinstance(v, dict)}


def _opportunity_maps(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    omega = payload.get("omega") if isinstance(payload.get("omega"), dict) else {}
    rows = omega.get("opportunities") if isinstance(omega.get("opportunities"), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    }


def _supply_score(stock: dict[str, Any], day_move: float, rvol: float) -> tuple[float, list[str]]:
    float_shares = _float_shares(stock)
    shares = _shares_outstanding(stock)
    insider = _insider_pct(stock)
    adv = _number(stock.get("avg_dollar_volume"))
    score = 25.0
    reasons: list[str] = []

    if float_shares > 0:
        if float_shares <= 3_000_000:
            score = 100.0
            reasons.append(f"Public float شديد الضيق ≈ {float_shares/1_000_000:.2f}M")
        elif float_shares <= 10_000_000:
            score = 92.0
            reasons.append(f"Public float ضيق ≈ {float_shares/1_000_000:.1f}M")
        elif float_shares <= 25_000_000:
            score = 78.0
            reasons.append(f"Float منخفض ≈ {float_shares/1_000_000:.1f}M")
        elif float_shares <= 50_000_000:
            score = 62.0
    elif adv > 0:
        # Inferred supply vacuum when reported float is missing/unreliable.
        if adv <= 3_000_000 and (abs(day_move) >= 3 or rvol >= 1.5):
            score = 78.0
            reasons.append("Supply vacuum مستنتج: سيولة دولار منخفضة وحساسية سعر عالية")
        elif adv <= 10_000_000 and rvol >= 1.5:
            score = 64.0
            reasons.append("سيولة تاريخية محدودة مع بداية اشتعال حجم")

    if insider >= 80:
        score = min(100.0, score + 18)
        reasons.append(f"Insider lock مرتفع جدًا ≈ {insider:.0f}%")
    elif insider >= 60:
        score = min(100.0, score + 12)
        reasons.append(f"Insider ownership مرتفع ≈ {insider:.0f}%")
    elif insider >= 40:
        score = min(100.0, score + 6)

    if float_shares > 0 and shares > 0 and float_shares / shares <= 0.15:
        score = min(100.0, score + 10)
        reasons.append("نسبة الـfloat إلى الأسهم القائمة صغيرة جدًا")
    return score, reasons


def _catalyst_score(cluster: dict[str, Any]) -> tuple[float, list[str]]:
    if not cluster:
        return 0.0, []
    quality = _number(cluster.get("catalyst_quality"))
    materiality = _number(cluster.get("materiality"))
    confidence = _number(cluster.get("confidence")) * 100.0
    age = _number(cluster.get("age_days"), 99.0)
    bias = str(cluster.get("directional_bias") or "").lower()
    reaction = str(cluster.get("reaction_state") or "").upper()
    dilution = _number(cluster.get("dilution_risk"))
    score = quality * 0.50 + materiality * 0.30 + min(100.0, confidence) * 0.20
    if bias != "bullish":
        score *= 0.55
    if age <= 1:
        score += 8
    elif age <= 3:
        score += 4
    elif age > 7:
        score -= 18
    if reaction == "NOT_YET_REPRICED":
        score += 8
    elif reaction == "REPRICING":
        score += 4
    elif reaction == "EXTENDED_CHASING_RISK":
        score -= 35
    if dilution >= 85:
        score -= 45
    elif dilution >= 60:
        score -= 15
    reasons = []
    headline = str(cluster.get("headline") or "").strip()
    if quality >= 75:
        reasons.append(f"Catalyst quality {quality:.0f}/100")
    if materiality >= 75:
        reasons.append(f"Materiality {materiality:.0f}/100")
    if headline:
        reasons.append(headline)
    return max(0.0, min(100.0, score)), reasons


def _ignition_score(stock: dict[str, Any], day_move: float, week_move: float, rvol: float) -> tuple[float, list[str]]:
    score = 20.0
    reasons: list[str] = []
    if rvol >= 4:
        score += 52
        reasons.append(f"RVOL مشتعل {rvol:.1f}x")
    elif rvol >= 2.5:
        score += 44
        reasons.append(f"RVOL قوي جدًا {rvol:.1f}x")
    elif rvol >= 1.8:
        score += 34
        reasons.append(f"RVOL قوي {rvol:.1f}x")
    elif rvol >= 1.25:
        score += 20
        reasons.append(f"RVOL بدأ يتسارع {rvol:.1f}x")

    if 2 <= day_move <= 8:
        score += 18
        reasons.append(f"السعر بدأ يتحرك بدون مطاردة +{day_move:.1f}%")
    elif 8 < day_move <= 25:
        score += 25
        reasons.append(f"إشعال سعري مبكر +{day_move:.1f}%")
    elif 25 < day_move <= 40:
        score += 12
        reasons.append(f"الحركة قوية لكن الاقتراب من المطاردة ارتفع +{day_move:.1f}%")
    elif day_move > 40:
        score -= 25
        reasons.append("الحركة اليومية صارت ممتدة")

    if bool(stock.get("breakout")):
        score += 10
        reasons.append("اختراق سعري مؤكد")
    state = str(stock.get("entry_state") or stock.get("setup_status") or "").lower()
    if state in {"early", "forming", "waiting"}:
        score += 8
    elif state in {"too_late", "extended"}:
        score -= 40
    if week_move > 80:
        score -= 25
    return max(0.0, min(100.0, score)), reasons


def _elasticity_score(stock: dict[str, Any], day_move: float) -> tuple[float, str | None]:
    adv = _number(stock.get("avg_dollar_volume"))
    if adv <= 0 or abs(day_move) < 1:
        return 0.0, None
    impact = abs(day_move) / max(0.5, adv / 1_000_000.0)
    score = min(100.0, impact * 12.0)
    if score >= 65:
        return score, "Price elasticity عالية: فلوس قليلة نسبيًا تحرك السعر بقوة"
    return score, None


@dataclass
class AsymmetricCandidate:
    symbol: str
    price: float
    score: float
    archetype: str
    supply: float
    catalyst: float
    ignition: float
    elasticity: float
    social: float
    day_move: float
    week_move: float
    rvol: float
    float_shares: float
    insider_pct: float
    cluster: dict[str, Any]
    reasons: list[str]


def select_asymmetric_candidates(payload: dict[str, Any]) -> list[AsymmetricCandidate]:
    min_score = _number(os.getenv("TELEGRAM_MIN_ASYMMETRIC_SCORE", "76"), 76.0)
    max_alerts = int(_number(os.getenv("TELEGRAM_MAX_ASYMMETRIC_ALERTS", "3"), 3.0))
    stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
    catalysts = _catalyst_maps(payload)
    opportunities = _opportunity_maps(payload)
    selected: list[AsymmetricCandidate] = []

    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        symbol = str(stock.get("symbol") or "").upper()
        if not symbol:
            continue
        day_move = _day_move(stock)
        week_move = _week_move(stock)
        rvol = _rvol(stock)
        supply, supply_reasons = _supply_score(stock, day_move, rvol)
        cluster = catalysts.get(symbol, {})
        catalyst, catalyst_reasons = _catalyst_score(cluster)
        ignition, ignition_reasons = _ignition_score(stock, day_move, week_move, rvol)
        elasticity, elasticity_reason = _elasticity_score(stock, day_move)
        social = min(100.0, _social_score(stock))
        insider = _insider_pct(stock)
        float_shares = _float_shares(stock)
        opportunity = opportunities.get(symbol, {})
        risk = _number((opportunity.get("dimensions") or {}).get("risk_penalty")) if isinstance(opportunity.get("dimensions"), dict) else 0.0
        dilution = _number(cluster.get("dilution_risk")) if cluster else 0.0
        reaction = str(cluster.get("reaction_state") or "").upper()
        state = str(stock.get("entry_state") or stock.get("setup_status") or "").lower()

        # Two independent paths learned from RGC-like and BNAI-like behavior.
        rgc_like = supply >= 78 and ignition >= 58 and (float_shares <= 10_000_000 if float_shares > 0 else elasticity >= 55)
        bnai_like = catalyst >= 72 and supply >= 62 and ignition >= 60
        squeeze_vacuum = supply >= 72 and ignition >= 72 and rvol >= 1.8
        if not (rgc_like or bnai_like or squeeze_vacuum):
            continue
        if dilution >= 85 or reaction == "EXTENDED_CHASING_RISK" or state in {"too_late", "extended"}:
            continue
        if day_move > 55 or week_move > 130 or risk > 72:
            continue

        score = supply * 0.34 + catalyst * 0.24 + ignition * 0.24 + elasticity * 0.10 + social * 0.08
        if rgc_like:
            score += 7
        if bnai_like:
            score += 7
        if squeeze_vacuum:
            score += 4
        score = max(0.0, min(100.0, score))
        if score < min_score:
            continue

        if rgc_like and bnai_like:
            archetype = "RGC+BNAI HYBRID — Broken Float + Catalyst"
        elif rgc_like:
            archetype = "RGC-LIKE — Broken Float / Supply Vacuum"
        elif bnai_like:
            archetype = "BNAI-LIKE — Catalyst + Micro-Float Repricing"
        else:
            archetype = "SQUEEZE VACUUM — Price/Volume Ignition"

        reasons = supply_reasons + catalyst_reasons + ignition_reasons
        if elasticity_reason:
            reasons.append(elasticity_reason)
        if social >= 20:
            reasons.append(f"Social acceleration {social:.0f}/100")
        selected.append(
            AsymmetricCandidate(
                symbol=symbol,
                price=_number(stock.get("price")),
                score=score,
                archetype=archetype,
                supply=supply,
                catalyst=catalyst,
                ignition=ignition,
                elasticity=elasticity,
                social=social,
                day_move=day_move,
                week_move=week_move,
                rvol=rvol,
                float_shares=float_shares,
                insider_pct=insider,
                cluster=cluster,
                reasons=list(dict.fromkeys(reason for reason in reasons if reason))[:8],
            )
        )

    selected.sort(key=lambda row: (row.score, row.supply, row.ignition, row.catalyst), reverse=True)
    return selected[:max_alerts]


def _fingerprint(candidate: AsymmetricCandidate) -> str:
    headline = str(candidate.cluster.get("headline") or "")[:100]
    return "|".join((candidate.symbol, candidate.archetype, f"{round(candidate.score/5)*5:.0f}", headline))


def _should_send(candidate: AsymmetricCandidate, sent: dict[str, Any]) -> bool:
    key = f"{candidate.symbol}:{candidate.archetype}"
    previous = sent.get(key) if isinstance(sent.get(key), dict) else {}
    if not previous:
        return True
    if str(previous.get("fingerprint") or "") != _fingerprint(candidate):
        return True
    return candidate.score >= _number(previous.get("score")) + 8


def _message(candidate: AsymmetricCandidate) -> str:
    float_text = f"{candidate.float_shares/1_000_000:.2f}M" if candidate.float_shares > 0 else "غير متوفر — نستخدم Supply Vacuum inferred"
    insider_text = f"{candidate.insider_pct:.0f}%" if candidate.insider_pct > 0 else "غير متوفر"
    catalyst_text = str(candidate.cluster.get("headline") or "لا يوجد خبر واحد مسيطر — النمط هيكلي/عرض وطلب")
    reasons = "\n".join(f"• {_safe(reason, 250)}" for reason in candidate.reasons)
    return (
        "🧨 <b>BLACK BOX Ω — ASYMMETRIC EXPLOSION</b>\n\n"
        f"<b>{_safe(candidate.symbol)}</b> — ${candidate.price:,.2f}\n"
        f"النمط: <b>{_safe(candidate.archetype)}</b>\n"
        f"Asymmetric Score: <b>{candidate.score:.0f}/100</b> <i>(ترتيب، مو احتمال)</i>\n\n"
        f"🧩 Supply Vacuum: <b>{candidate.supply:.0f}/100</b>\n"
        f"⚡ Catalyst: <b>{candidate.catalyst:.0f}/100</b>\n"
        f"🔥 Ignition: <b>{candidate.ignition:.0f}/100</b>\n"
        f"🪶 Price Elasticity: <b>{candidate.elasticity:.0f}/100</b>\n"
        f"📣 Social: <b>{candidate.social:.0f}/100</b>\n\n"
        f"اليوم: <b>{candidate.day_move:+.1f}%</b> | RVOL: <b>{candidate.rvol:.2f}x</b>\n"
        f"Public Float: <b>{_safe(float_text)}</b> | Insider: <b>{_safe(insider_text)}</b>\n\n"
        f"📰 <b>المحفز</b>\n{_safe(catalyst_text, 700)}\n\n"
        f"🔎 <b>ليش يشبه انفجارات RGC/BNAI؟</b>\n{reasons}\n\n"
        "الحالة: <b>ASYMMETRIC WATCH — راقب التفعيل ولا تطارد شمعة ممتدة</b>"
    )


def notify(payload_path: Path, state_path: Path = DEFAULT_STATE_PATH) -> int:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print("Asymmetric: Telegram token missing; skip")
        return 0
    payload = _load(payload_path, {})
    if not isinstance(payload, dict) or not payload:
        print("Asymmetric: payload unavailable; skip")
        return 0
    candidates = select_asymmetric_candidates(payload)
    state = _load(state_path, {"sent": {}})
    if not isinstance(state, dict):
        state = {"sent": {}}
    sent = state.setdefault("sent", {})
    count = 0
    if candidates:
        chat_id = _resolve_chat_id(token)
        for candidate in candidates:
            if not _should_send(candidate, sent):
                continue
            _send(token, chat_id, _message(candidate))
            key = f"{candidate.symbol}:{candidate.archetype}"
            sent[key] = {
                "fingerprint": _fingerprint(candidate),
                "score": round(candidate.score, 1),
                "sent_at": _utc_now(),
            }
            count += 1
    state["last_run_at"] = _utc_now()
    state["last_candidates"] = [candidate.symbol for candidate in candidates]
    state["last_sent_count"] = count
    _save(state_path, state)
    print(f"Asymmetric: candidates={len(candidates)} sent={count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="RGC/BNAI-style asymmetric explosion detector")
    parser.add_argument("--payload", default="public/data/latest.json")
    parser.add_argument("--state", default=str(DEFAULT_STATE_PATH))
    args = parser.parse_args()
    try:
        return notify(Path(args.payload), Path(args.state))
    except requests.RequestException as exc:
        print(f"Asymmetric Telegram network error: {exc}")
        return 2
    except Exception as exc:
        print(f"Asymmetric detector error: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
