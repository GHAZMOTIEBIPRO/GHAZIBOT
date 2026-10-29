"""Quality checks for OHLCV bars before anything is computed from them.

One rule set, two runners. Each rule is a function over a normalised frame
that marks the valid rows. pandera runs the same functions as named checks
when it is installed (`OHLCV_SCHEMA`); otherwise they run directly. The issue
codes are identical either way.

Four outcomes are kept apart (see `.claude/skills/ghazi-data-quality`):
- SOURCE_UNAVAILABLE: the fetch returned nothing usable (no key, gate, HTTP error);
- DATA_ERROR: bars arrived but some break a rule (they are dropped, with a code and count);
- INSUFFICIENT_HISTORY: valid bars, too few for the indicator asked for;
- OK.
A compute error (our indicator vs the reference) is tested separately and
never reported as a data problem.

Expected differences that are not errors: IEX bars carry one exchange's
volume and range (labelled by `feed`); a missing minute bar means no trade.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from typing import Any

import pandas as pd

PRICE_COLS = ("open", "high", "low", "close")
# Common split / reverse-split ratios. A close-to-next-open jump within 3% of one of
# them, on data that is not split-adjusted, is flagged for review (not dropped).
SPLIT_RATIOS = (2, 3, 4, 5, 8, 10, 15, 20, 1.5)
SPLIT_TOLERANCE = 0.03


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.map(lambda v: None if isinstance(v, bool) else v), errors="coerce").astype(float)


def _prices(d: pd.DataFrame) -> pd.DataFrame:
    return d[list(PRICE_COLS)].apply(_num)


def _finite(d: pd.DataFrame) -> pd.Series:
    return _prices(d).apply(lambda c: c.map(math.isfinite)).all(axis=1)


# code -> function(frame) -> boolean Series (True = row passes). A row with a missing
# price fails NON_FINITE_PRICE only, so each bad row carries its primary code.
ROW_RULES: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "NON_FINITE_PRICE": _finite,
    "NON_POSITIVE_PRICE": lambda d: ~_finite(d) | (_prices(d) > 0).all(axis=1),
    "HIGH_BELOW_BODY": lambda d: ~_finite(d) | (_num(d["high"]) >= _prices(d)[["open", "close", "low"]].max(axis=1)),
    "LOW_ABOVE_BODY": lambda d: ~_finite(d) | (_num(d["low"]) <= _prices(d)[["open", "close", "high"]].min(axis=1)),
    "NEGATIVE_VOLUME": lambda d: _num(d["volume"]).isna() | (_num(d["volume"]) >= 0),
}
RULE_AR = {"NON_FINITE_PRICE": "سعر مفقود أو غير رقمي", "NON_POSITIVE_PRICE": "سعر صفري أو سالب",
           "HIGH_BELOW_BODY": "القمة أقل من الافتتاح أو الإغلاق", "LOW_ABOVE_BODY": "القاع أعلى من الافتتاح أو الإغلاق",
           "NEGATIVE_VOLUME": "حجم سالب", "DUPLICATE_TIMESTAMP": "شمعة مكررة بنفس الوقت",
           "OUT_OF_ORDER": "شموع غير مرتبة زمنيًا", "NAIVE_TIMESTAMP": "وقت بلا منطقة زمنية",
           "UNPARSEABLE_TIMESTAMP": "وقت غير مقروء"}


def _pandera_schema() -> Any:
    try:
        import pandera.pandas as pa
    except ImportError:
        return None
    return pa.DataFrameSchema(
        {c: pa.Column(nullable=True, coerce=False) for c in (*PRICE_COLS, "volume")},
        # name only: pandera reports `error` text instead of the name when both are set
        checks=[pa.Check(fn, name=code) for code, fn in ROW_RULES.items()],
        strict=False)


OHLCV_SCHEMA = _pandera_schema()


def _ts(value: Any) -> datetime | None | str:
    """Bar start as aware UTC; 'NAIVE' when no zone; None when unreadable."""
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return "NAIVE"
    return dt.astimezone(timezone.utc)


def _frame(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    recs = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        recs.append({"start_raw": r.get("t", r.get("start", r.get("date"))),
                     **{c: r.get(c, r.get(c[0])) for c in PRICE_COLS},
                     "volume": r.get("volume", r.get("v"))})
    return pd.DataFrame(recs, columns=["start_raw", *PRICE_COLS, "volume"])


def _row_failures(df: pd.DataFrame) -> tuple[dict[str, list[int]], str]:
    """Row indices failing each rule, by pandera when available."""
    if df.empty:
        return {}, "none"
    if OHLCV_SCHEMA is not None:
        import pandera.errors as pe

        try:
            OHLCV_SCHEMA.validate(df[[*PRICE_COLS, "volume"]], lazy=True)
            return {}, "pandera"
        except pe.SchemaErrors as err:
            cases = err.failure_cases
            out: dict[str, list[int]] = {}
            for code in ROW_RULES:
                idx = cases.loc[cases["check"] == code, "index"].dropna()
                if len(idx):
                    out[code] = sorted({int(i) for i in idx})
            return out, "pandera"
    out = {}
    for code, fn in ROW_RULES.items():
        ok = fn(df).fillna(False)
        bad = [int(i) for i in df.index[~ok.astype(bool)]]
        if bad:
            out[code] = bad
    return out, "python"


def _split_suspects(clean: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    closes, opens = clean["close"].astype(float).tolist(), clean["open"].astype(float).tolist()
    for i in range(1, len(clean)):
        if closes[i - 1] <= 0:
            continue
        ratio = opens[i] / closes[i - 1]
        for r in SPLIT_RATIOS:
            if abs(ratio * r - 1) <= SPLIT_TOLERANCE or abs(ratio / r - 1) <= SPLIT_TOLERANCE:
                out.append({"bar": clean["start"].iloc[i].isoformat(), "open_over_prev_close": round(ratio, 4),
                            "near_ratio": f"1:{r}" if ratio < 1 else f"{r}:1"})
                break
    return out


def check_bars(rows: Any, *, interval: str, as_of: datetime, fetch_status: str = "OK", feed: str | None = None,
               adjustment: str | None = None, need: int = 0,
               session_close: Callable[[str], datetime | None] | None = None) -> dict[str, Any]:
    """Check one series. `interval` is e.g. '5m', '1h', '1d'; `as_of` is the provider time minus its delay.

    Returns the report and, under 'clean', the completed rows that pass every rule
    (oldest first, one per timestamp), ready for computation.
    """
    base = {"interval": interval, "feed": feed, "adjustment": adjustment, "as_of": as_of.isoformat(),
            "issues": [], "completed": 0, "forming": 0, "split_suspects": [], "history": {"have": 0, "need": need},
            "clean": []}
    if fetch_status != "OK" or rows is None:
        return {**base, "status": "SOURCE_UNAVAILABLE", "reason": fetch_status}
    df = _frame(rows)
    if df.empty:
        return {**base, "status": "SOURCE_UNAVAILABLE", "reason": "NO_BARS_RETURNED"}
    issues: list[dict[str, Any]] = []
    parsed = df["start_raw"].map(_ts)
    naive = parsed.map(lambda v: v == "NAIVE")
    unreadable = parsed.isna()
    for code, mask in (("NAIVE_TIMESTAMP", naive), ("UNPARSEABLE_TIMESTAMP", unreadable)):
        if mask.any():
            issues.append({"code": code, "rows": int(mask.sum()), "sample": df.loc[mask, "start_raw"].astype(str).head(3).tolist()})
    df["start"] = parsed.where(~(naive | unreadable), None)
    failures, engine = _row_failures(df)
    bad = set()
    for code, idx in failures.items():
        bad |= set(idx)
        issues.append({"code": code, "rows": len(idx), "sample": df.loc[idx, "start_raw"].astype(str).head(3).tolist()})
    keep = df[df["start"].notna() & ~df.index.isin(bad)].copy()
    backwards = sum(1 for a, b in pairwise(keep["start"].tolist()) if b < a)
    if backwards:
        issues.append({"code": "OUT_OF_ORDER", "rows": backwards, "sample": []})
    dup = keep["start"].duplicated(keep="last")
    if dup.any():
        issues.append({"code": "DUPLICATE_TIMESTAMP", "rows": int(dup.sum()),
                       "sample": [s.isoformat() for s in keep.loc[dup, "start"].head(3)]})
    keep = keep[~dup].sort_values("start")
    # completed vs forming: a bar counts once its end has passed the provider's as-of time
    if interval == "1d":
        def done(start: datetime) -> bool:
            close = session_close(start.date().isoformat()) if session_close else None
            return close is not None and close <= as_of
    else:
        minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}[interval]

        def done(start: datetime) -> bool:
            return start + timedelta(minutes=minutes) <= as_of
    completed_mask = keep["start"].map(done).astype(bool)
    completed = keep[completed_mask]
    split = [] if adjustment in ("split", "all") else _split_suspects(completed)
    status = ("DATA_ERROR" if issues else
              "INSUFFICIENT_HISTORY" if len(completed) < need else "OK")
    clean = [{"t": s, **{c: float(completed[c].iloc[i]) for c in PRICE_COLS},
              "volume": (None if pd.isna(completed["volume"].iloc[i]) else float(completed["volume"].iloc[i]))}
             for i, s in enumerate(completed["start"])]
    return {**base, "status": status, "engine": engine, "issues": issues, "completed": len(completed),
            "forming": int((~completed_mask).sum()), "split_suspects": split,
            "history": {"have": len(completed), "need": need, "sufficient": len(completed) >= need},
            "last_completed_start": completed["start"].iloc[-1].isoformat() if len(completed) else None,
            "usable": len(completed) >= max(need, 1), "clean": clean}


def summary(report: dict[str, Any]) -> dict[str, Any]:
    """The report without the rows (safe to publish as counts)."""
    return {k: v for k, v in report.items() if k != "clean"}
