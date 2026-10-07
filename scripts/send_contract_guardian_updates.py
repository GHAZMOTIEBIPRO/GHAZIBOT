from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from scripts.telegram_transport import edit_html_message, send_html_message


STAGE_AR = {
    "WATCH": "مراقبة",
    "CONFIRMED": "مؤكد",
    "ACTIVE": "نشط",
    "T1_HIT": "تحقق الهدف الأول",
    "T2_HIT": "تحقق الهدف الثاني",
    "T3_HIT": "تحقق الهدف الثالث",
    "INVALIDATED": "أُلغي السيناريو",
    "EXPIRED": "انتهت صلاحية العقد",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe(value: Any, limit: int = 480) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _load(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value


def _save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temp.replace(path)


def _target_price(row: dict[str, Any], key: str) -> float:
    target_map = row.get("target_map")
    target_map = target_map if isinstance(target_map, dict) else {}
    value = target_map.get(key)
    return _number(value.get("price")) if isinstance(value, dict) else 0.0


def _premium_target_text(row: dict[str, Any], key: str) -> str:
    payload = row.get("premium_targets")
    payload = payload if isinstance(payload, dict) else {}
    targets = payload.get("targets")
    targets = targets if isinstance(targets, dict) else {}
    target = targets.get(key)
    if not isinstance(target, dict):
        return "—"
    low = _number(target.get("premium_low"), float("nan"))
    base = _number(target.get("premium_base"), float("nan"))
    high = _number(target.get("premium_high"), float("nan"))
    if not all(math.isfinite(value) for value in (low, base, high)):
        return "—"
    return f"{low:.2f}$–{high:.2f}$ (أساس {base:.2f}$)"


def _fingerprint(row: dict[str, Any]) -> str:
    impact = (
        row.get("catalyst_health")
        if isinstance(row.get("catalyst_health"), dict)
        else {}
    )
    chart = row.get("chart_health") if isinstance(row.get("chart_health"), dict) else {}
    thesis = row.get("explosion_thesis") if isinstance(row.get("explosion_thesis"), dict) else {}
    raw = "|".join(
        [
            str(chart.get("state") or ""),
            str(thesis.get("verification") or ""),
            str(thesis.get("headline") or ""),
            str(thesis.get("event_date") or ""),
            str(row.get("quote_history_count") or 0),
            str(row.get("unstamped_research_count") or 0),
            str(row.get("contract_symbol") or ""),
            str(row.get("stage") or ""),
            str(bool(row.get("stage_provisional"))),
            str(bool(row.get("entry_reference_verified"))),
            f"{_number(row.get('last_mark')):.2f}",
            f"{_number(row.get('last_underlying_price')):.2f}",
            f"{round(_number(row.get('last_return_pct')) / 3.0) * 3:.0f}",
            str(bool(row.get("iv_crush_risk"))),
            str(bool(row.get("data_stale"))),
            f"{_number(impact.get('impact_score')):.0f}",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _message(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").upper()
    side = str(row.get("side") or "").upper()
    contract = str(row.get("contract_symbol") or "")
    stage = str(row.get("stage") or "WATCH").upper()
    stage_ar = STAGE_AR.get(stage, stage)
    entry = _number(row.get("entry_premium_reference"))
    entry_verified = row.get("entry_reference_verified") is True
    mark = _number(row.get("last_mark"), float("nan"))
    indicative_mark = _number(row.get("last_indicative_mark"), float("nan"))
    ret = _number(row.get("last_return_pct"), float("nan"))
    mfe = _number(row.get("mfe_pct"), float("nan"))
    mae = _number(row.get("mae_pct"), float("nan"))
    spot = _number(row.get("last_underlying_price"), float("nan"))
    strike = _number(row.get("strike"))
    expiration = str(row.get("expiration") or "")[:10]
    quote_age = row.get("quote_age_minutes")
    quote_age_text = (
        f"{_number(quote_age):.0f}د"
        if quote_age is not None
        else "غير معروف"
    )
    impact = (
        row.get("catalyst_health")
        if isinstance(row.get("catalyst_health"), dict)
        else {}
    )
    impact_score = impact.get("impact_score")
    impact_text = (
        f"{_number(impact_score):.0f}/100"
        if impact_score is not None
        else "—"
    )

    icon = "🟢" if side == "CALL" else "🔴"
    mark_text = f"{mark:.2f}$" if math.isfinite(mark) and mark > 0 else "—"
    ret_text = (
        f"{ret:+.1f}%" if math.isfinite(ret)
        and not row.get("data_stale") and entry_verified else "—"
    )
    spot_text = f"{spot:.2f}$" if math.isfinite(spot) and spot > 0 else "—"

    t1 = _target_price(row, "t1")
    t2 = _target_price(row, "t2")
    t3 = _target_price(row, "t3")
    invalidation = _target_price(row, "invalidation")
    t1_text = f"{t1:.2f}$" if t1 > 0 else "—"
    t2_text = f"{t2:.2f}$" if t2 > 0 else "—"
    t3_text = f"{t3:.2f}$" if t3 > 0 else "—"
    invalidation_text = f"{invalidation:.2f}$" if invalidation > 0 else "—"

    mfe_text = f"{mfe:+.1f}%" if math.isfinite(mfe) else "—"
    mae_text = f"{mae:+.1f}%" if math.isfinite(mae) else "—"
    lines = [
        "🛡 <b>BLACK BOX Ω — متابعة العقد</b>",
        f"{icon} <b>{_safe(symbol, 20)} {side}</b> | الحالة: <b>{_safe(stage_ar, 80)}</b>",
        (
            f"🎯 <b>{strike:g} {side}</b> • {_safe(expiration, 20)}"
            f" | العقد <b>{_safe(contract, 80)}</b>"
        ),
        (
            f"💵 سعر الاختيار المرجعي <b>{entry:.2f}$</b> → سعر العقد الموثق زمنيًا <b>{mark_text}</b>"
            f" | الأداء <b>{ret_text}</b>"
        ),
        f"📈 MFE <b>{mfe_text}</b> | MAE <b>{mae_text}</b> | السهم <b>{spot_text}</b>",
        "",
        "<b>أهداف السهم المجمدة من التوصية الأصلية</b>",
        f"• T1 {t1_text} | T2 {t2_text} | T3 {t3_text}",
        f"• إبطال السيناريو: <b>{invalidation_text}</b>",
        "",
        "<b>تقدير قيمة العقد عند الأهداف</b>",
        f"• T1: {_safe(_premium_target_text(row, 't1'), 120)}",
        f"• T2: {_safe(_premium_target_text(row, 't2'), 120)}",
        f"• T3: {_safe(_premium_target_text(row, 't3'), 120)}",
    ]

    headline = str(impact.get("headline") or "").strip()
    source = str(impact.get("source") or "").strip()
    lines.extend(
        [
            "",
            f"🧨 قوة المحفز: <b>{impact_text}</b>",
            f"📰 {_safe(headline or 'لا يوجد محفز رسمي مرتبط محفوظ', 520)}",
            f"المصدر: <b>{_safe(source or '—', 120)}</b>",
        ]
    )

    chart = row.get("chart_health") if isinstance(row.get("chart_health"), dict) else {}
    thesis = row.get("explosion_thesis") if isinstance(row.get("explosion_thesis"), dict) else {}
    chart_label = str(chart.get("label_ar") or "مؤشرات الشارت غير متاحة")
    rvol = _number(chart.get("rvol"), float("nan"))
    pressure = _number(chart.get("breakout_pressure_score"), float("nan"))
    rvol_text = f"{rvol:.2f}×" if math.isfinite(rvol) else "—"
    pressure_text = f"{pressure:.0f}/100" if math.isfinite(pressure) else "—"
    lines.extend([
        "",
        "<b>📊 قراءة الشارت — سياق بحثي من آخر فحص</b>",
        f"{_safe(chart_label, 140)} | RVOL <b>{rvol_text}</b> | ضغط الاختراق <b>{pressure_text}</b>",
    ])
    proof = str(thesis.get("proof_ar") or "").strip()
    if proof:
        lines.append(f"📋 حالة الخبر: <b>{_safe(proof, 150)}</b>")
    drivers = thesis.get("drivers_ar") if isinstance(thesis.get("drivers_ar"), list) else []
    risks = thesis.get("risks_ar") if isinstance(thesis.get("risks_ar"), list) else []
    if drivers:
        lines.append("العوامل: " + _safe("؛ ".join(str(x) for x in drivers[:2]), 280))
    if risks:
        lines.append("المخاطر: " + _safe("؛ ".join(str(x) for x in risks[:2]), 280))
    source_url = str(thesis.get("primary_url") or "")
    if source_url.startswith(("https://", "http://")):
        lines.append(f'🔗 <a href="{_safe(source_url, 500)}">فتح المصدر الأصلي للخبر</a>')
    count = int(_number(row.get("quote_history_count")))
    lines.append(f"📚 سجل العقد: <b>{count}</b> لقطة بتوقيت تسعير موثّق (بحثي)")
    unstamped = int(_number(row.get("unstamped_research_count")))
    if unstamped:
        lines.append(
            f"📓 رصد مجاني غير مؤرّخ: <b>{unstamped}</b> تغيّر سعر جُمِع وقت الفحص؛ "
            "ليس تاريخ تداول أو سعرًا لحظيًا مؤكّدًا."
        )

    if row.get("stage_provisional"):
        lines.append(
            "⚠️ <b>حالة الهدف أو الإبطال مبدئية: توقيت سعر السهم غير موثّق؛ "
            "لا تُحسب نتيجة نهائية.</b>"
        )
    if not entry_verified:
        lines.append(
            "⚠️ <b>سعر بداية العقد مرجعي وغير موثّق؛ "
            "لا تتوفر نسبة ربح أو خسارة قابلة للتحقق.</b>"
        )
    if math.isfinite(indicative_mark) and indicative_mark > 0:
        lines.append(
            f"📒 قيمة إرشادية من آخر فحص: <b>{indicative_mark:.2f}$</b>"
            " — دون إثبات وقت تسعيرها."
        )
    if row.get("iv_crush_risk"):
        lines.append("⚠️ <b>خطر IV Crush ظاهر مقارنةً بوقت التوصية.</b>")
    if row.get("data_stale"):
        lines.append(
            f"⚠️ بيانات العقد قديمة/غير مكتملة؛ عمر الـQuote: <b>{quote_age_text}</b>."
        )
    else:
        lines.append(f"🕒 عمر الـQuote: <b>{quote_age_text}</b>.")

    lines.extend(
        [
            "",
            "<i>الأهداف السعرية للعقد نطاقات سيناريو بحثية وليست سعراً مضموناً. "
            "المتابعة لا تتجاوز بوابة V11 ولا تعدّل التوصية الأصلية بأثر رجعي.</i>",
        ]
    )
    return "\n".join(lines)


def _rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    for key in ("active", "terminal_recent"):
        values = report.get(key)
        if isinstance(values, list):
            combined.extend(row for row in values if isinstance(row, dict))
    unique: dict[str, dict[str, Any]] = {}
    for row in combined:
        contract = str(row.get("contract_symbol") or "").strip().upper()
        if contract:
            unique[contract] = row
    return list(unique.values())


def send_updates(report: dict[str, Any], state: dict[str, Any]) -> dict[str, int]:
    registry = state.setdefault("contracts", {})
    if not isinstance(registry, dict):
        registry = {}
        state["contracts"] = registry

    sent = 0
    edited = 0
    unchanged = 0
    for row in _rows(report):
        contract = str(row.get("contract_symbol") or "").strip().upper()
        if not contract:
            continue
        fingerprint = _fingerprint(row)
        previous = registry.get(contract)
        previous = previous if isinstance(previous, dict) else {}
        if str(previous.get("fingerprint") or "") == fingerprint:
            unchanged += 1
            continue

        text_value = _message(row)
        message_id = previous.get("message_id")
        if message_id:
            try:
                result = edit_html_message(int(message_id), text_value)
                registry[contract] = {
                    **previous,
                    "fingerprint": fingerprint,
                    "message_id": result.message_id or int(message_id),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "stage": row.get("stage"),
                }
                edited += 1
                continue
            except requests.HTTPError as exc:
                response = exc.response
                if response is None or response.status_code != 400:
                    raise

        result = send_html_message(text_value)
        registry[contract] = {
            "fingerprint": fingerprint,
            "message_id": result.message_id,
            "created_at": previous.get("created_at")
            or datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "stage": row.get("stage"),
            "symbol": row.get("symbol"),
            "side": row.get("side"),
        }
        sent += 1

    state.update(
        {
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_sent": sent,
            "last_edited": edited,
            "last_unchanged": unchanged,
            "state_schema": "contract_guardian_telegram_v1",
        }
    )
    return {"sent": sent, "edited": edited, "unchanged": unchanged}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send or edit one Telegram lifecycle card per tracked option contract."
    )
    parser.add_argument(
        "--report",
        default="public/data/contract_guardian.json",
    )
    parser.add_argument(
        "--state",
        default="data/live/contract_guardian_telegram_state.json",
    )
    args = parser.parse_args()

    report = _load(Path(args.report), {})
    if not isinstance(report, dict):
        raise RuntimeError("Contract Guardian report must be a JSON object")
    state_path = Path(args.state)
    state = _load(state_path, {"contracts": {}})
    if not isinstance(state, dict):
        state = {"contracts": {}}

    try:
        result = send_updates(report, state)
    finally:
        _save(state_path, state)

    print(
        "Contract Guardian Telegram: "
        f"sent={result['sent']} edited={result['edited']} "
        f"unchanged={result['unchanged']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
