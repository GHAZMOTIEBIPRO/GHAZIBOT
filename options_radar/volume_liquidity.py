"""Volume & liquidity context from completed OHLCV bars (research only).

Everything here is inferred from candles and their volume. There is no
order book, tape or quote depth: volume profile levels are estimates,
sweeps are price-action proxies, and nothing claims institutional intent.
Inputs must already be completed bars indexed in America/New_York.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any

import pandas as pd

PROFILE_BINS = 24
VALUE_AREA = 0.70
MIN_PRIOR_SESSIONS = 3
RVOL_HIGH = 1.5
RVOL_LOW = 0.7
BREAKOUT_VOLUME_MULTIPLE = 1.5
OPENING_RANGE_BARS = 2  # two completed 15m bars = 09:30-10:00


def _f(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sessions(m15: pd.DataFrame) -> list[pd.DataFrame]:
    if m15 is None or m15.empty or "Volume" not in m15:
        return []
    return [frame for _, frame in m15.groupby(m15.index.date) if not frame.empty]


def volume_profile(bars: pd.DataFrame, *, bins: int = PROFILE_BINS) -> dict[str, Any] | None:
    """POC / VAH / VAL estimate: each bar's volume spread uniformly over its
    high-low range (no intrabar trade data exists)."""
    if bars is None or bars.empty:
        return None
    low, high = float(bars["Low"].min()), float(bars["High"].max())
    total = float(bars["Volume"].clip(lower=0).sum())
    if not (high > low > 0) or total <= 0:
        return None
    step = (high - low) / bins
    hist = [0.0] * bins
    for row in bars.itertuples():
        lo, hi, vol = float(row.Low), float(row.High), max(0.0, float(row.Volume))
        first = min(bins - 1, int((lo - low) / step))
        last = min(bins - 1, int((hi - low) / step))
        share = vol / (last - first + 1)
        for i in range(first, last + 1):
            hist[i] += share
    poc = max(range(bins), key=lambda i: hist[i])
    lo_i = hi_i = poc
    covered = hist[poc]
    while covered < VALUE_AREA * total and (lo_i > 0 or hi_i < bins - 1):
        below = hist[lo_i - 1] if lo_i > 0 else -1.0
        above = hist[hi_i + 1] if hi_i < bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            covered += above
        else:
            lo_i -= 1
            covered += below
    return {
        "poc": round(low + (poc + 0.5) * step, 4),
        "vah": round(low + (hi_i + 1) * step, 4),
        "val": round(low + lo_i * step, 4),
        "bin_size": round(step, 4),
        "bars_used": len(bars),
        "method": "OHLCV_UNIFORM_RANGE_ESTIMATE",
    }


def same_time_rvol(sessions: list[pd.DataFrame]) -> dict[str, Any] | None:
    """Latest session's cumulative volume up to its last completed bar time
    versus the median cumulative volume of prior sessions at that time."""
    if len(sessions) < MIN_PRIOR_SESSIONS + 1:
        return None
    current = sessions[-1]
    cutoff = current.index[-1].time()
    now_volume = float(current["Volume"].sum())
    prior = []
    for frame in sessions[:-1]:
        upto = frame[[t.time() <= cutoff for t in frame.index]]
        if len(upto) == len(current):  # same completed-bar count only
            prior.append(float(upto["Volume"].sum()))
    if len(prior) < MIN_PRIOR_SESSIONS or median(prior) <= 0:
        return None
    rvol = now_volume / median(prior)
    return {
        "rvol": round(rvol, 2),
        "state": "HIGH" if rvol >= RVOL_HIGH else "LOW" if rvol < RVOL_LOW else "NORMAL",
        "basis": f"same-time cumulative 15m volume vs median of {len(prior)} prior sessions",
        "through_bar_start": current.index[-1].isoformat(),
    }


def _breakout(current: pd.DataFrame, level: float, baseline: float, side: str) -> str | None:
    crossed = current["Close"] > level if side == "up" else current["Close"] < level
    if not crossed.any():
        return None
    bar = current.loc[crossed].iloc[0]
    still = (current["Close"].iloc[-1] > level) if side == "up" else (current["Close"].iloc[-1] < level)
    if not still:
        return "FAILED_BREAKOUT" if side == "up" else "FAILED_BREAKDOWN"
    confirmed = baseline > 0 and float(bar["Volume"]) >= BREAKOUT_VOLUME_MULTIPLE * baseline
    kind = "BREAKOUT" if side == "up" else "BREAKDOWN"
    return f"{kind}_VOLUME_CONFIRMED" if confirmed else f"{kind}_VOLUME_UNCONFIRMED"


def liquidity_context(daily: pd.DataFrame, m15: pd.DataFrame) -> dict[str, Any]:
    sessions = _sessions(m15)
    if not sessions or daily is None or daily.empty:
        return {"status": "INSUFFICIENT_BARS"}
    current = sessions[-1]
    session_day = current.index[-1].date()
    prior_daily = daily[[d.date() < session_day for d in daily.index]]
    if prior_daily.empty:
        return {"status": "INSUFFICIENT_BARS"}
    prev = prior_daily.iloc[-1]
    prev_high, prev_low, prev_close = _f(prev["High"]), _f(prev["Low"]), _f(prev["Close"])
    last_close = _f(current["Close"].iloc[-1])
    typical = (current["High"] + current["Low"] + current["Close"]) / 3
    vol = current["Volume"].clip(lower=0)
    vwap = float((typical * vol).sum() / vol.sum()) if vol.sum() > 0 else None
    prior_bars = pd.concat(sessions[:-1]) if len(sessions) > 1 else current.iloc[0:0]
    baseline = float(prior_bars["Volume"].median()) if not prior_bars.empty else 0.0

    opening = None
    if len(current) > OPENING_RANGE_BARS:
        first = current.iloc[:OPENING_RANGE_BARS]
        orh, orl = float(first["High"].max()), float(first["Low"].min())
        opening = {"high": round(orh, 4), "low": round(orl, 4),
                   "status": "ABOVE" if last_close > orh else "BELOW" if last_close < orl else "INSIDE"}

    sweep = None
    if prev_high and ((current["High"] > prev_high) & (current["Close"] < prev_high)).any() \
            and last_close < prev_high:
        sweep = "ABOVE_PRIOR_HIGH_REJECTED"
    elif prev_low and ((current["Low"] < prev_low) & (current["Close"] > prev_low)).any() \
            and last_close > prev_low:
        sweep = "BELOW_PRIOR_LOW_REJECTED"

    breakout = (_breakout(current, prev_high, baseline, "up") if prev_high else None) or \
               (_breakout(current, prev_low, baseline, "down") if prev_low else None)
    open_price = _f(current["Open"].iloc[0])
    return {
        "status": "OK",
        "session_date": session_day.isoformat(),
        "last_bar_start": current.index[-1].isoformat(),
        "last_close": round(last_close, 4) if last_close else None,
        "volume": same_time_rvol(sessions),
        "session_vwap": round(vwap, 4) if vwap else None,
        "vwap_position": (None if not vwap or not last_close else
                          "ABOVE" if last_close > vwap else "BELOW" if last_close < vwap else "AT"),
        "profile_session": volume_profile(current),
        "profile_composite": volume_profile(pd.concat(sessions)),
        "prior_day": {"high": prev_high, "low": prev_low, "close": prev_close},
        "gap_pct": (round((open_price / prev_close - 1) * 100, 2)
                    if open_price and prev_close else None),
        "opening_range": opening,
        "sweep_proxy": sweep,
        "breakout": breakout,
        "inference_only": True,
    }


def read_ar(ctx: dict[str, Any]) -> list[str]:
    """Short Arabic reading. Never states accumulation/distribution as fact."""
    if ctx.get("status") != "OK":
        return ["لا توجد شموع مكتملة كافية لقراءة الفوليوم والسيولة."]
    out = []
    vol = ctx.get("volume") or {}
    if vol:
        word = {"HIGH": "مرتفع", "LOW": "منخفض", "NORMAL": "طبيعي"}[vol["state"]]
        out.append(f"الحجم {word} (RVOL {vol['rvol']}) مقارنة بنفس الوقت في الجلسات السابقة.")
    breakout = ctx.get("breakout") or ""
    if breakout.endswith("VOLUME_CONFIRMED"):
        out.append("الاختراق/الكسر لقمة أو قاع الأمس جاء بحجم أعلى من المعتاد.")
    elif breakout.endswith("VOLUME_UNCONFIRMED"):
        out.append("الاختراق/الكسر حدث بحجم غير كافٍ؛ يحتاج تأكيدًا.")
    elif breakout.startswith("FAILED"):
        out.append("اختراق/كسر لم يصمد وعاد السعر داخل نطاق الأمس (احتمال اختراق كاذب).")
    if ctx.get("sweep_proxy"):
        out.append("تجاوز السعر قمة/قاع الأمس ثم ارتد: سحب سيولة محتمل كاستنتاج من السعر فقط.")
    if ctx.get("vwap_position") in {"ABOVE", "BELOW"}:
        out.append("السعر " + ("فوق" if ctx["vwap_position"] == "ABOVE" else "تحت") + " VWAP الجلسة.")
    out.append("القراءة استنتاج فني من الشموع والحجم؛ لا تتوفر بيانات دفتر الأوامر أو الصفقات.")
    return out
