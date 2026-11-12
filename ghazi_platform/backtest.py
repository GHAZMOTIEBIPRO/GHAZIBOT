"""Event-time backtest lab on the user's own daily bars.

Honesty rules (AGENTS.md "Outcome and learning rules"):
- no look-ahead: a signal uses bars up to and including the signal bar's close;
  entry is the NEXT bar's open;
- a bar that touches both the stop and the target is AMBIGUOUS (daily bars cannot
  order them) and is never counted as a win;
- costs (commission + slippage, in basis points per side) are always applied;
- results are counts with their denominators; below MIN_SAMPLE trades no rate is
  shown, and no rate is ever presented as a future probability;
- the in-sample / out-of-sample split is by time, never shuffled.
Long-only in this alpha.
"""
from __future__ import annotations

import math
import statistics
from typing import Any

MIN_SAMPLE = 30
STRATEGIES = {
    "ema_cross": {"name_ar": "تقاطع متوسطين أسيين",
                  "params": {"fast": (5, 100, 20), "slow": (10, 250, 50), "stop_atr": (0.0, 10.0, 2.0),
                             "target_atr": (0.0, 20.0, 0.0), "max_hold": (1, 250, 60)}},
    "breakout": {"name_ar": "اختراق قمة N جلسة",
                 "params": {"lookback": (5, 250, 20), "stop_atr": (0.5, 10.0, 2.0), "target_atr": (0.5, 20.0, 3.0),
                            "max_hold": (1, 250, 20)}},
}
COST_LIMITS = {"commission_bps": (0.0, 100.0, 1.0), "slippage_bps": (0.0, 200.0, 5.0)}


class BacktestError(ValueError):
    def __init__(self, message_ar: str):
        super().__init__(message_ar)
        self.message_ar = message_ar


def _bounded(raw: dict[str, Any], spec: dict[str, tuple]) -> dict[str, float]:
    out = {}
    for key, (lo, hi, default) in spec.items():
        value = raw.get(key, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise BacktestError(f"قيمة غير صالحة للمعامل {key}.") from None
        if not math.isfinite(value) or not lo <= value <= hi:
            raise BacktestError(f"المعامل {key} يجب أن يكون بين {lo} و{hi}.")
        out[key] = int(value) if isinstance(default, int) else value
    return out


def validate(strategy: str, params: dict[str, Any]) -> dict[str, Any]:
    if strategy not in STRATEGIES:
        raise BacktestError("استراتيجية غير معروفة.")
    p = _bounded(params, STRATEGIES[strategy]["params"])
    p.update(_bounded(params, COST_LIMITS))
    if strategy == "ema_cross" and p["fast"] >= p["slow"]:
        raise BacktestError("المتوسط السريع يجب أن يكون أقصر من البطيء.")
    split = params.get("oos_fraction", 0.0)
    try:
        split = float(split)
    except (TypeError, ValueError):
        raise BacktestError("نسبة خارج العينة غير صالحة.") from None
    if not (split == 0.0 or 0.1 <= split <= 0.5):
        raise BacktestError("نسبة خارج العينة يجب أن تكون 0 أو بين 0.1 و0.5.")
    p["oos_fraction"] = split
    return p


def ema(values: list[float], span: int) -> list[float]:
    k = 2 / (span + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def atr_series(bars: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    """Wilder-free simple ATR: mean true range of the last `period` bars, causal."""
    trs: list[float] = []
    out: list[float | None] = []
    for i, b in enumerate(bars):
        prev = bars[i - 1]["close"] if i else b["close"]
        trs.append(max(b["high"] - b["low"], abs(b["high"] - prev), abs(b["low"] - prev)))
        out.append(sum(trs[-period:]) / period if len(trs) >= period + 1 else None)
    return out


def signals(strategy: str, bars: list[dict[str, Any]], p: dict[str, Any]) -> list[int]:
    """Indices t whose close produces an entry signal (computed from bars[:t+1] only)."""
    closes = [b["close"] for b in bars]
    out = []
    if strategy == "ema_cross":
        fast, slow = ema(closes, p["fast"]), ema(closes, p["slow"])
        for t in range(p["slow"], len(bars)):
            if fast[t] > slow[t] and fast[t - 1] <= slow[t - 1]:
                out.append(t)
    else:
        n = p["lookback"]
        for t in range(n, len(bars)):
            if closes[t] > max(b["high"] for b in bars[t - n:t]):
                out.append(t)
    return out


def _cross_downs(bars: list[dict[str, Any]], p: dict[str, Any]) -> list[int]:
    closes = [b["close"] for b in bars]
    fast, slow = ema(closes, p["fast"]), ema(closes, p["slow"])
    return [j for j in range(1, len(bars)) if fast[j] < slow[j] and fast[j - 1] >= slow[j - 1]]


def simulate(strategy: str, bars: list[dict[str, Any]], p: dict[str, Any], *,
             cost_multiplier: float = 1.0) -> list[dict[str, Any]]:
    atr = atr_series(bars)
    downs = _cross_downs(bars, p) if strategy == "ema_cross" else []
    side_cost = (p["commission_bps"] + p["slippage_bps"]) * cost_multiplier / 10_000
    trades: list[dict[str, Any]] = []
    busy_until = -1
    for t in signals(strategy, bars, p):
        if t <= busy_until or t + 1 >= len(bars) or atr[t] is None:
            continue
        e = t + 1
        entry = bars[e]["open"]
        stop = entry - p["stop_atr"] * atr[t] if p["stop_atr"] > 0 else None
        target = entry + p["target_atr"] * atr[t] if p["target_atr"] > 0 else None
        cross_exit = next((j for j in downs if j > t), None)
        last = min(len(bars) - 1, e + int(p["max_hold"]) - 1)
        outcome, exit_px, exit_i = None, None, None
        for j in range(e, last + 1):
            b = bars[j]
            # exit signal at bar j-1's close is executed at bar j's open, before anything intrabar
            if cross_exit is not None and j == cross_exit + 1:
                outcome, exit_px, exit_i = "SIGNAL_EXIT", b["open"], j
                break
            if j > e and stop is not None and b["open"] <= stop:
                outcome, exit_px, exit_i = "STOP_GAP", b["open"], j
                break
            if j > e and target is not None and b["open"] >= target:
                outcome, exit_px, exit_i = "TARGET_GAP", b["open"], j
                break
            hit_stop = stop is not None and b["low"] <= stop
            hit_target = target is not None and b["high"] >= target
            if hit_stop and hit_target:
                outcome, exit_px, exit_i = "AMBIGUOUS", None, j
                break
            if hit_stop:
                outcome, exit_px, exit_i = "STOP", stop, j
                break
            if hit_target:
                outcome, exit_px, exit_i = "TARGET", target, j
                break
        if outcome is None:
            if last == len(bars) - 1 and last - e + 1 < p["max_hold"]:
                # the data ends before the trade's rule-based exit: not a result
                outcome, exit_px, exit_i = "OPEN_AT_END", None, last
            else:
                outcome, exit_px, exit_i = "TIME_EXIT", bars[last]["close"], last
        trade = {"signal_date": bars[t]["date"], "entry_date": bars[e]["date"], "entry": round(entry, 4),
                 "stop": round(stop, 4) if stop is not None else None,
                 "target": round(target, 4) if target is not None else None,
                 "exit_date": bars[exit_i]["date"], "outcome": outcome,
                 "exit": round(exit_px, 4) if exit_px is not None else None, "bars_held": exit_i - e + 1}
        if exit_px is not None:
            gross = exit_px / entry - 1
            trade["gross_return_pct"] = round(gross * 100, 4)
            trade["net_return_pct"] = round(((exit_px * (1 - side_cost)) / (entry * (1 + side_cost)) - 1) * 100, 4)
        trades.append(trade)
        busy_until = exit_i
    return trades


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    resolved = [t for t in trades if "net_return_pct" in t]
    ambiguous = sum(1 for t in trades if t["outcome"] == "AMBIGUOUS")
    still_open = sum(1 for t in trades if t["outcome"] == "OPEN_AT_END")
    wins = sum(1 for t in resolved if t["net_return_pct"] > 0)
    rets = [t["net_return_pct"] for t in resolved]
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for r in rets:
        equity *= 1 + r / 100
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
    n = len(resolved)
    out = {"signals": len(trades), "resolved": n, "ambiguous_same_bar": ambiguous, "open_at_end": still_open,
           "net_positive": wins, "net_non_positive": n - wins,
           "mean_net_return_pct": round(statistics.fmean(rets), 4) if rets else None,
           "median_net_return_pct": round(statistics.median(rets), 4) if rets else None,
           "compounded_net_return_pct": round((equity - 1) * 100, 4) if rets else None,
           "max_drawdown_pct": round(max_dd * 100, 4) if rets else None,
           "sample_sufficient": n >= MIN_SAMPLE, "min_sample": MIN_SAMPLE}
    if n >= MIN_SAMPLE:
        out["net_positive_share"] = {"count": wins, "of": n,
                                     "note_ar": "تكرار تاريخي على بياناتك بعد التكاليف؛ ليس احتمالًا للمستقبل."}
    else:
        out["net_positive_share"] = None
        out["insufficient_note_ar"] = f"العينة {n} صفقة أقل من {MIN_SAMPLE}؛ لا تُعرض نسبة."
    return out


def run(strategy: str, bars: list[dict[str, Any]], raw_params: dict[str, Any], *,
        allow_oos: bool, allow_cost_sensitivity: bool) -> dict[str, Any]:
    p = validate(strategy, raw_params)
    if p["oos_fraction"] and not allow_oos:
        raise BacktestError("تقسيم داخل/خارج العينة غير مشمول في خطتك.")
    if len(bars) < 60:
        raise BacktestError("يلزم 60 شمعة يومية على الأقل للاختبار.")
    trades = simulate(strategy, bars, p)
    result: dict[str, Any] = {
        "schema": "ghazi.platform.backtest.v1", "strategy": strategy, "strategy_ar": STRATEGIES[strategy]["name_ar"],
        "params": p, "bars": len(bars), "period": {"from": bars[0]["date"], "to": bars[-1]["date"]},
        "all": summarize(trades), "trades": trades[-500:],
        "assumptions_ar": [
            "الدخول عند افتتاح الجلسة التالية لإشارة الإغلاق (بلا نظر للمستقبل).",
            f"التكلفة لكل جهة: عمولة {p['commission_bps']} وانزلاق {p['slippage_bps']} نقطة أساس.",
            "الشمعة التي تلمس الوقف والهدف معًا تُسجل «غامضة» ولا تُحسب ربحًا.",
            "شراء فقط؛ لا رافعة؛ صفقة واحدة في كل وقت.",
            "البيانات من رفع المستخدم ولم يتحقق النظام من تعديلات التجزئة والتوزيعات.",
        ],
        "probability": None, "execution_authority": False,
    }
    if p["oos_fraction"]:
        cut = bars[int(len(bars) * (1 - p["oos_fraction"]))]["date"]
        result["split"] = {"oos_starts": cut,
                           "in_sample": summarize([t for t in trades if t["signal_date"] < cut]),
                           "out_of_sample": summarize([t for t in trades if t["signal_date"] >= cut]),
                           "note_ar": "التقسيم زمني؛ المعاملات مختارة مسبقًا ولم تُحسَّن على خارج العينة."}
    if allow_cost_sensitivity:
        result["cost_sensitivity"] = [{"cost_multiplier": m, **{k: v for k, v in summarize(
            simulate(strategy, bars, p, cost_multiplier=m)).items() if k in (
                "resolved", "mean_net_return_pct", "compounded_net_return_pct", "max_drawdown_pct")}}
            for m in (0.0, 1.0, 2.0, 3.0)]
    return result
