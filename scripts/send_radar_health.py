from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from options_radar.telegram_transport import send_html_message

RANK = {"HEALTHY": 0, "DEGRADED": 1, "CRITICAL": 2}


def _load(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(destination)


def _send(text: str) -> None:
    send_html_message(text)


def _status_ar(status: str) -> str:
    return {
        "HEALTHY": "سليم",
        "DEGRADED": "متدهور جزئيًا",
        "CRITICAL": "حرج",
    }.get(status, status)


def _provider_ar(status: str) -> str:
    return {
        "CRITICAL_NO_OPTION_DATA": "لا توجد بيانات أوبشن قابلة للاستخدام",
        "FALLBACK_ONLY": "مصدر احتياطي/متأخر فقط",
        "LIVE_QUOTES_NO_TRADE_FLOW": "أسعار حية لكن تدفق الصفقات غير مكتمل",
        "LIVE_FLOW_READY": "بيانات حية وتدفق صفقات جاهز",
    }.get(status, status or "غير معروف")


def _reason_ar(reason: str) -> str:
    text = str(reason or "").strip()
    lowered = text.lower()
    if "no usable option-chain source" in lowered:
        return "لا يوجد حاليًا مصدر عقود أوبشن صالح للاستخدام."
    if "only delayed, indicative, unofficial, or fallback option data" in lowered:
        return "مصادر الأوبشن الحالية احتياطية أو متأخرة أو استرشادية فقط."
    if "live option quotes are available, but trade+nbbo flow evidence is not active" in lowered:
        return "أسعار الأوبشن حية، لكن تدفق الصفقات مع NBBO غير مفعل بالكامل."
    if "a live trade/quote flow source is active" in lowered:
        return "مصدر حي للصفقات والأسعار يعمل حاليًا."
    match = re.search(r"(\d+) chain\(s\) are yahoo/yfinance-only fallback", lowered)
    if match:
        return f"عدد {match.group(1)} سلسلة عقود تعتمد على Yahoo/YFinance فقط كمصدر احتياطي."
    match = re.search(r"(\d+) chain\(s\) are delayed, indicative, or unofficial", lowered)
    if match:
        return f"عدد {match.group(1)} سلسلة عقود بياناتها متأخرة أو استرشادية أو غير رسمية."
    match = re.search(r"(\d+) chain\(s\) have successful cross-source retrieval", lowered)
    if match:
        return f"عدد {match.group(1)} سلسلة عقود تم تأكيدها من أكثر من مصدر."
    match = re.search(r"(\d+) chain\(s\) report opra-backed evidence", lowered)
    if match:
        return f"عدد {match.group(1)} سلسلة عقود لديها دليل مدعوم ببيانات OPRA."
    if lowered.startswith("streaming source active:"):
        source = text.split(":", 1)[-1].strip()
        return f"مصدر البث الحي النشط: {source}."
    if any(ord(ch) > 127 for ch in text):
        return text
    return "يوجد سبب تقني مسجل في النظام؛ راجع السجل التفصيلي عند الحاجة."


def maybe_send(path_name: str, payload: dict[str, Any], state: dict[str, Any]) -> bool:
    health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
    current = str(health.get("status") or "UNKNOWN").upper()
    if current not in RANK:
        return False
    states = state.setdefault("paths", {})
    previous = str((states.get(path_name) or {}).get("status") or "UNKNOWN").upper()
    changed = previous != current
    should_send = changed and (current != "HEALTHY" or previous in {"DEGRADED", "CRITICAL"})
    if should_send:
        icon = "🚨" if current == "CRITICAL" else ("⚠️" if current == "DEGRADED" else "✅")
        label = "مسار الأسهم" if path_name == "stocks" else "مسار عقود الأوبشن"
        reasons = [str(item) for item in health.get("reasons", []) if str(item).strip()]
        readiness = payload.get("provider_readiness") if isinstance(payload.get("provider_readiness"), dict) else {}

        lines = [
            f"{icon} <b>بلاك بوكس Ω | صحة البوت</b>",
            "",
            f"المسار: <b>{html.escape(label)}</b>",
            f"الحالة الآن: <b>{html.escape(_status_ar(current))}</b>",
        ]
        if previous in RANK:
            lines.append(f"الحالة السابقة: {html.escape(_status_ar(previous))}")

        if path_name == "options" and readiness:
            provider_status = str(readiness.get("status") or "")
            quote_ready = readiness.get("production_quote_ready") is True
            flow_ready = readiness.get("production_flow_ready") is True
            sources = [str(value) for value in readiness.get("sources", []) if str(value).strip()]
            lines.extend(
                [
                    "",
                    "🛰 <b>وضع بيانات الأوبشن</b>",
                    f"• المصدر: <b>{html.escape(_provider_ar(provider_status))}</b>",
                    f"• أسعار صالحة للتنبيه الإنتاجي: <b>{'نعم ✅' if quote_ready else 'لا ❌'}</b>",
                    f"• تدفق صفقات حي كامل: <b>{'نعم ✅' if flow_ready else 'لا/غير مكتمل ⚠️'}</b>",
                ]
            )
            if sources:
                lines.append(f"• المصادر النشطة: {html.escape(', '.join(sources[:4]))}")

        if reasons:
            lines.extend(["", "🔎 <b>السبب</b>"])
            for reason in reasons[:4]:
                lines.append(f"• {html.escape(_reason_ar(reason)[:360])}")

        lines.extend(["", "🧭 <b>وش يعني هذا لك؟</b>"])
        if current == "HEALTHY":
            lines.append("المسار عاد للعمل بصورة سليمة، ويمكنه استئناف التنبيهات وفق شروطه المعتادة.")
        elif path_name == "options" and readiness.get("production_quote_ready") is not True:
            lines.append("لن أعتمد عقود الأوبشن كتوصيات إنتاجية من هذا المصدر. سيستمر الجمع والبحث والتعلم فقط إلى أن تصبح البيانات الحية صالحة.")
        elif current == "CRITICAL":
            lines.append("المسار غير موثوق حاليًا؛ اعتبر تنبيهاته متوقفة حتى وصول رسالة تعافٍ.")
        else:
            lines.append("المسار يعمل جزئيًا، لكن جودة أو توفر بعض البيانات أقل من المطلوب؛ خذ هذا في الحسبان عند قراءة أي تنبيه.")

        _send("\n".join(lines))
    states[path_name] = {
        "status": current,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": health.get("metrics", {}),
    }
    return should_send


def main() -> None:
    parser = argparse.ArgumentParser(description="Notify only on BLACK BOX radar health transitions")
    parser.add_argument("--path", choices=("stocks", "options"), required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    payload = _load(args.payload)
    state = _load(args.state) or {"paths": {}}
    sent = maybe_send(args.path, payload, state)
    _save(args.state, state)
    print(f"Radar health transition: path={args.path} sent={int(sent)}")


if __name__ == "__main__":
    main()
