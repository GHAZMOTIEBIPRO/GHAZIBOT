"""Owner-private, evidence-gated Arabic market digest.

Ideas: multi-timeframe filters (SPY Signal Platform), candidate ranking and
outcome-readable presentation (MarketDigest), and no-spam short scanning
(Momentum Radar). Original implementation; no third-party source copied.

No fetching, public state, order execution, option signals, or probabilities.
All numeric levels and volume facts come from validated local research cards.
"""
from __future__ import annotations

import html
import math
from typing import Any

from options_radar.analysis_card import scope_ar

REQUIRED_FRAMES = ("daily", "1h", "15m", "5m")
MAX_TELEGRAM_CHARS = 3900


def _number(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        return None
    return float(raw)


def assess(card: dict[str, Any]) -> dict[str, Any]:
    """Rank *research watches*, never CALL/PUT trades or claimed probabilities."""
    base = {"symbol": str(card.get("symbol") or ""), "state": "WAIT", "bias": "NEUTRAL",
            "aligned_frames": 0, "volume_confirmed": False, "win_probability": None,
            "execution_authority": False, "reasons": []}
    if not card.get("available"):
        return {**base, "reasons": ["لا توجد قراءة سعرية مكتملة"]}
    quality = card.get("data_quality") or {}
    if any((quality.get(frame) or {}).get("status") not in (None, "OK") or
           (quality.get(frame) or {}).get("issues") for frame in ("daily", "5m")):
        return {**base, "reasons": ["جودة بيانات الشموع لا تسمح بالترشيح"]}
    frames = ((card.get("interpretation") or {}).get("frames") or {})
    trends = [(frames.get(k) or {}).get("trend") for k in REQUIRED_FRAMES]
    volume = ((card.get("interpretation") or {}).get("liquidity") or {})
    rv = volume.get("volume") or {}
    confirmed = (volume.get("status") == "OK" and rv.get("state") == "HIGH"
                 and _number(rv.get("rvol")) is not None
                 and _number(rv.get("rvol")) >= 1.5)
    if len(trends) != len(REQUIRED_FRAMES) or any(t not in {"UP", "DOWN"} for t in trends):
        return {**base, "aligned_frames": max(trends.count("UP"), trends.count("DOWN")),
                "reasons": ["أطر اتجاه ناقصة أو مختلطة"]}
    aligned = max(trends.count("UP"), trends.count("DOWN"))
    if aligned != len(REQUIRED_FRAMES):
        return {**base, "aligned_frames": aligned, "reasons": ["اتجاه الأطر غير متوافق"]}
    direction = trends[0]
    breakout = volume.get("breakout")
    required_break = "BREAKOUT_VOLUME_CONFIRMED" if direction == "UP" else "BREAKDOWN_VOLUME_CONFIRMED"
    # A breakout from a previous session with no RVOL confirmation is not a watch.
    if not confirmed or breakout != required_break:
        return {**base, "aligned_frames": aligned, "bias": direction, "reasons":
                ["الاتجاه متوافق لكن الحجم/اختراق المستوى غير مؤكد"]}
    levels = {item.get("name"): _number(item.get("value"))
              for item in ((card.get("observed") or {}).get("levels") or [])
              if isinstance(item, dict)}
    if not (levels.get("prior_day_high") and levels.get("prior_day_low")):
        return {**base, "aligned_frames": aligned, "bias": direction,
                "reasons": ["مستويات الأمس الموثقة غير متاحة"]}
    return {**base, "state": "WATCH_UP" if direction == "UP" else "WATCH_DOWN",
            "bias": direction, "aligned_frames": aligned, "volume_confirmed": True,
            "reasons": ["توافق اتجاه الأطر، حجم مرتفع واختراق مستوى الأمس بحجم"]}


def _price(value: Any) -> str:
    n = _number(value)
    return f"{n:,.2f}" if n is not None and n > 0 else "غير متاح"


def _line(card: dict[str, Any], result: dict[str, Any]) -> str:
    symbol = html.escape(result["symbol"], quote=True)
    scope = html.escape(scope_ar(card.get("feed_scope")), quote=True)
    session = html.escape(str(card.get("data_as_of") or "غير متاح"), quote=True)
    levels = {item.get("name"): item.get("value")
              for item in ((card.get("observed") or {}).get("levels") or [])
              if isinstance(item, dict)}
    vol = ((card.get("interpretation") or {}).get("liquidity") or {})
    rv = vol.get("volume") or {}
    rvol = _number(rv.get("rvol"))
    volume_label = (f"RVOL {rvol:.2f} (تقديري من الشموع)"
                    if vol.get("status") == "OK" and rvol is not None else "الحجم غير مكتمل")
    state_ar = {"WATCH_UP": "مراقبة صعود مشروطة", "WATCH_DOWN": "مراقبة هبوط مشروطة",
                "WAIT": "انتظار"}
    label = state_ar[result["state"]]
    # No live option flow or institutional sweep is inferred from candle volume.
    missing_options = any(m.get("item") == "options" for m in (card.get("missing") or []) if isinstance(m, dict))
    opt = "؛ الأوبشن غير متحقق" if missing_options else ""
    return (f"{symbol} ({scope}، جلسة {session}) — {label}\n"
            f"توافق {result['aligned_frames']}/{len(REQUIRED_FRAMES)} أطر؛ "
            f"مقاومة {_price(levels.get('prior_day_high'))}، "
            f"دعم {_price(levels.get('prior_day_low'))}؛ {volume_label}{opt}.\n"
            "المستوى شرط مراقبة وليس أمر دخول؛ يلزم تحديث البيانات قبل أي قرار.")


def render(cards: dict[str, dict[str, Any]], last_closed_session: Any, *,
           max_chars: int = MAX_TELEGRAM_CHARS) -> str:
    """Return complete Telegram-safe blocks; never truncate one mid-number or mid-HTML.

    The existing delivery path must independently authorize both the source
    and the owner's one-to-one chat. This function performs no transmission.
    """
    if max_chars < 280 or max_chars > 4096:
        raise ValueError("max_chars must be between 280 and 4096")
    date = html.escape(str(last_closed_session or "غير متاح"), quote=True)
    lines = [f"<b>خطة اليوم الخاصة — {date}</b>",
             "مصدر: Alpaca؛ شموع مكتملة متأخرة 16 دقيقة أو أكثر؛ استخدام شخصي فقط.",
             "WATCH = مراقبة لا توصية CALL/PUT. التوافق ليس احتمالًا؛ بلا احتمال نجاح ولا توصية تنفيذ.",
             "السيولة وRVOL استنتاجان من الشموع والحجم، وليسا سجل أوامر أو صفقات مؤسسية."]
    eligible = [c for c in (cards or {}).values() if isinstance(c, dict) and c.get("available")]
    scored = [(assess(c), c) for c in eligible]
    scored.sort(key=lambda x: (x[0]["state"] == "WAIT", -x[0]["aligned_frames"], x[0]["symbol"]))
    omitted = 0
    for outcome, card in scored:
        line = _line(card, outcome)
        if len("\n\n".join([*lines, line])) + 80 <= max_chars:
            lines.append(line)
        else:
            omitted += 1
    if omitted:
        suffix = f"لم تُعرض {omitted} رموز لضيق رسالة تيليجرام؛ لا يعني ذلك غياب البيانات."
        if len("\n\n".join([*lines, suffix])) <= max_chars:
            lines.append(suffix)
    return "\n\n".join(lines)
