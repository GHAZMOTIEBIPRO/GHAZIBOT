"""Research-only Arabic market briefing formatter; never invent market data."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return "غير متاح"
    return f"{value:,.2f}"


def format_daily_brief(payload: dict[str, Any]) -> str:
    """Format evidence-backed rows. Missing data remains explicitly missing."""
    generated = payload.get("generated_at") or "غير معروف"
    rows = payload.get("symbols") or []
    lines = [f"BLACK BOX Ω | التقرير اليومي", f"وقت إنشاء التقرير: {generated}", "تحليل بحثي وليس توصية تنفيذية"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        source = str(row.get("source") or "غير معروف")
        quote_time = str(row.get("quote_time") or "غير معروف")
        direction = str(row.get("direction") or "غير محسوم")
        lines.extend([f"\n{symbol} | الاتجاه: {direction}",
                      f"السعر: {_number(row.get('price'))} | الدعم: {_number(row.get('support'))} | المقاومة: {_number(row.get('resistance'))}",
                      f"الهدف: {_number(row.get('target'))} | الإبطال: {_number(row.get('invalidation'))}",
                      f"المصدر: {source} | وقت بيانات السعر: {quote_time}"])
        if not row.get("quote_time"):
            lines.append("تنبيه: حداثة السعر غير مثبتة؛ لا تستخدم للتنفيذ.")
    if not rows:
        lines.append("لا تتوفر بيانات مؤهلة للتقرير؛ لم يتم إنشاء إشارات.")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Evidence-backed JSON with symbols list")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    print(format_daily_brief(data))
