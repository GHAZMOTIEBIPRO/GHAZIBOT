"""Arabic reading of model GEX levels and a forward test of their usefulness.

Everything here is derived from the ghazi_gex_multi engine output: Cboe
delayed spot/IV and prior-session open interest (inputs), with gamma,
levels and hedging estimated by a Black-Scholes model under an assumed
dealer sign. Nothing here is a measured dealer position, and nothing has
signal authority. The forward test compares the model walls with a
same-width band centred on spot, so a "wall" only counts as informative if
it beats that naive band on later sessions.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

MIN_SESSIONS_FOR_VERDICT = 20


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pct(level: float | None, spot: float) -> float | None:
    return round((level / spot - 1) * 100, 2) if level is not None else None


def interpret(engine: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(engine, dict) or engine.get("available") is not True:
        return None
    spot = _num(engine.get("spot"))
    if spot is None or spot <= 0:
        return None
    flip, call_wall, put_wall = (_num(engine.get(k)) for k in ("gamma_flip", "call_wall", "put_wall"))
    net = _num(engine.get("net_gex"))
    gci = _num(engine.get("gci"))
    zdte = _num(engine.get("zdte_share_abs_gex"))
    lines: list[str] = []
    if flip is not None:
        if spot > flip:
            lines.append(f"السعر فوق نقطة الانقلاب التقديرية ({flip:,.0f}): نظام جاما موجب في النموذج، "
                         "وعادة ما يميل التحوط إلى تهدئة الحركة وتضييق النطاق.")
        else:
            lines.append(f"السعر تحت نقطة الانقلاب التقديرية ({flip:,.0f}): نظام جاما سالب في النموذج، "
                         "وقد يضخم التحوط الحركة في الاتجاهين؛ تقلب أعلى محتمل.")
    if call_wall is not None and call_wall > spot:
        lines.append(f"Call Wall {call_wall:,.0f} (+{_pct(call_wall, spot)}%): مستوى مقاومة نموذجي محتمل، ليس سقفًا مضمونًا.")
    if put_wall is not None and put_wall < spot:
        lines.append(f"Put Wall {put_wall:,.0f} ({_pct(put_wall, spot)}%): مستوى دعم نموذجي محتمل، ليس قاعًا مضمونًا.")
    if call_wall is not None and put_wall is not None and not (put_wall < spot < call_wall):
        lines.append("السعر ليس بين الجدارين؛ قراءة الجدران كنطاق غير صالحة الآن.")
    if net is not None:
        side = "عكس" if net > 0 else "مع"
        lines.append(f"ضغط التحوط التقديري: نحو {abs(net):,.1f} مليار $ لكل حركة 1% ({side} اتجاه الحركة) "
                     "بافتراض أن المتعاملين مشترون للكول وبائعون للبوت.")
    if gci is not None:
        lines.append("الجاما " + ("مركزة في عدد قليل من السترايكات" if gci >= 0.1 else "موزعة على سترايكات كثيرة")
                     + f" (GCI {gci * 100:.1f}%).")
    if zdte is not None:
        lines.append(f"حصة أقرب انتهاء ({engine.get('front_expiry') or '—'}) من الجاما: {zdte * 100:.0f}%؛ "
                     "أثرها يتلاشى بعد انتهائها.")
    return {
        "spot": spot,
        "regime": engine.get("gamma_regime"),
        "distance_pct": {"gamma_flip": _pct(flip, spot), "call_wall": _pct(call_wall, spot),
                         "put_wall": _pct(put_wall, spot)},
        "hedging_pressure_bn_per_1pct": round(abs(net), 2) if net is not None else None,
        "hedging_direction_model": ("DAMPENING" if net is not None and net > 0
                                    else "AMPLIFYING" if net is not None else None),
        "relevant_expirations": {"front": engine.get("front_expiry"),
                                 "count": engine.get("expirations_used"),
                                 "front_share_abs_gex": zdte},
        "measured_inputs": ["spot (Cboe delayed)", "implied volatility (Cboe delayed)",
                            "open interest (prior session)"],
        "model_outputs": ["net GEX", "gamma flip", "call/put walls", "hedging pressure", "regime"],
        "reading_ar": lines,
        "is_measured_dealer_position": False,
    }


def history_entry(engine: dict[str, Any], generated_at: str) -> dict[str, Any] | None:
    if not isinstance(engine, dict) or engine.get("available") is not True:
        return None
    return {key: engine.get(key) for key in ("spot", "gamma_flip", "call_wall", "put_wall",
                                             "net_gex", "gamma_regime", "front_expiry")} | {
        "generated_at": generated_at}


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def validate_levels(history: list[dict[str, Any]], daily_bars: list[dict[str, Any]],
                    next_session_of) -> dict[str, Any]:
    """For each session, take the last snapshot published before that
    session (via `next_session_of(datetime) -> 'YYYY-MM-DD' | None`) and check
    the session's realized high/low against the model walls and against a
    same-width band centred on the snapshot spot."""
    bars = {str(b.get("time")): b for b in daily_bars if isinstance(b, dict)}
    by_session: dict[str, dict[str, Any]] = {}
    for entry in history:
        engine = entry.get("engine_levels") if isinstance(entry.get("engine_levels"), dict) else None
        stamp = _parse((engine or {}).get("generated_at"))
        if engine is None or stamp is None:
            continue
        session = next_session_of(stamp)
        if session is None:
            continue
        current = by_session.get(session)
        if current is None or _parse(current["generated_at"]) < stamp:
            by_session[session] = engine
    walls_hit = band_hit = tested = 0
    ranges = {"positive": [], "negative": []}
    for session, engine in sorted(by_session.items()):
        bar = bars.get(session)
        spot, call_wall, put_wall = (_num(engine.get(k)) for k in ("spot", "call_wall", "put_wall"))
        high, low = (_num(bar.get(k)) for k in ("high", "low")) if bar else (None, None)
        if None in (spot, call_wall, put_wall, high, low) or not (put_wall < spot < call_wall):
            continue
        tested += 1
        walls_hit += put_wall <= low and high <= call_wall
        half = (call_wall - put_wall) / 2
        band_hit += spot - half <= low and high <= spot + half
        regime = engine.get("gamma_regime")
        if regime in ranges:
            ranges[regime].append((high - low) / spot * 100)
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    return {
        "sessions_tested": tested,
        "walls_contained_range_rate": round(walls_hit / tested, 4) if tested else None,
        "same_width_centred_band_rate": round(band_hit / tested, 4) if tested else None,
        "mean_range_pct_positive_regime": mean(ranges["positive"]),
        "mean_range_pct_negative_regime": mean(ranges["negative"]),
        "regime_sessions": {k: len(v) for k, v in ranges.items()},
        "verdict": ("INSUFFICIENT_SAMPLE" if tested < MIN_SESSIONS_FOR_VERDICT
                    else "WALLS_BEAT_BASELINE" if walls_hit > band_hit else "NO_EDGE_OVER_BASELINE"),
        "minimum_sessions_for_verdict": MIN_SESSIONS_FOR_VERDICT,
        "method": "last snapshot before each session vs that session's realized high/low; "
                  "baseline is a band of equal width centred on the snapshot spot",
    }
