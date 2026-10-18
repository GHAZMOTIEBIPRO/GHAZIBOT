"""Free daily and 15-minute US index research map for public GHAZI RADAR.

Uses the existing yfinance transport, Pandas and exchange-calendars stack;
Yahoo quotes can be delayed/limited. This is an independent RESEARCH layer,
never OPRA trade flow, execution-grade evidence, or a CALL/PUT instruction.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

NY = ZoneInfo("America/New_York")
SYMBOLS = {
    "SPX": ("^GSPC", "S&P 500 Index", "index"),
    "NDX": ("^NDX", "Nasdaq 100 Index", "index"),
    "DJI": ("^DJI", "Dow Jones Industrial Average", "index"),
    "RUT": ("^RUT", "Russell 2000 Index", "index"),
    "VIX": ("^VIX", "Cboe Volatility Index", "volatility_index"),
    "SPY": ("SPY", "SPDR S&P 500 ETF", "etf_proxy"),
    "QQQ": ("QQQ", "Invesco Nasdaq 100 ETF", "etf_proxy"),
    "IWM": ("IWM", "iShares Russell 2000 ETF", "etf_proxy"),
    "DIA": ("DIA", "SPDR Dow Jones ETF", "etf_proxy"),
}
REQUIRED = ("Open", "High", "Low", "Close")
FIVE_MIN_SYMBOLS = ("SPX", "NDX", "SPY", "QQQ")  # Bounded: only two core indices and ETFs


def clean_bars(frame: pd.DataFrame | None, *, intraday: bool) -> pd.DataFrame:
    if frame is None or frame.empty or not isinstance(frame.index, pd.DatetimeIndex):
        return pd.DataFrame()
    out = frame.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = out.columns.get_level_values(0)
    if not all(name in out for name in REQUIRED):
        return pd.DataFrame()
    if intraday and out.index.tz is None:
        return pd.DataFrame()  # Never guess an intraday timezone.
    if out.index.tz is None:
        out.index = out.index.tz_localize(NY)
    else:
        out.index = out.index.tz_convert(NY)
    for name in (*REQUIRED, "Volume"):
        if name in out:
            out[name] = pd.to_numeric(out[name], errors="coerce")
    out = out.dropna(subset=list(REQUIRED)).sort_index()
    out = out.loc[~out.index.duplicated(keep="last")]
    out = out[(out["Close"] > 0) & (out["High"] >= out["Low"]) &
              (out["High"] >= out["Close"]) & (out["Low"] <= out["Close"])]
    if "Volume" not in out:
        out["Volume"] = 0.0
    out["Volume"] = out["Volume"].clip(lower=0).fillna(0)
    return out


def safe(value: object, digits: int = 3) -> float | None:
    try:
        result = float(value)
        return round(result, digits) if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def rsi14(series: pd.Series) -> float | None:
    if len(series) < 16:
        return None
    change = series.diff()
    gain = change.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    g, l = safe(gain.iloc[-1], 9), safe(loss.iloc[-1], 9)
    if g is None or l is None:
        return None
    if l == 0:
        return 100.0 if g > 0 else 50.0
    return round(100.0 - 100.0 / (1.0 + g/l), 2)


def atr14(frame: pd.DataFrame) -> float | None:
    if len(frame) < 15:
        return None
    previous = frame["Close"].shift(1)
    tr = pd.concat([
        frame["High"] - frame["Low"],
        (frame["High"]-previous).abs(),
        (frame["Low"]-previous).abs(),
    ], axis=1).max(axis=1)
    result = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean().iloc[-1]
    return safe(result)


def technical(frame: pd.DataFrame, *, fast: int = 20, slow: int = 50) -> dict:
    if frame is None or frame.empty:
        return {"bias": "UNAVAILABLE", "rsi14": None, "ema_fast": None,
                "ema_slow": None, "fast_period": fast, "slow_period": slow,
                "atr14": None}
    prices = frame["Close"]
    ema20 = safe(prices.ewm(span=fast, adjust=False).mean().iloc[-1]) if len(prices) >= fast else None
    ema50 = safe(prices.ewm(span=slow, adjust=False).mean().iloc[-1]) if len(prices) >= slow else None
    close = safe(prices.iloc[-1])
    rsi = rsi14(prices)
    bias = "MIXED"
    if close is not None and ema20 is not None and ema50 is not None and rsi is not None:
        if close > ema20 > ema50 and rsi >= 55:
            bias = "UP"
        elif close < ema20 < ema50 and rsi <= 45:
            bias = "DOWN"
    elif len(prices) < slow:
        bias = "INSUFFICIENT"
    return {"bias": bias, "rsi14": rsi, "ema_fast": ema20, "ema_slow": ema50,
            "fast_period": fast, "slow_period": slow, "atr14": atr14(frame)}


def completed_daily(daily: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Never treat today's unclosed daily candle as confirmed."""
    if daily.empty:
        return daily
    local = now.astimezone(NY)
    cutoff = local.replace(hour=16, minute=30, second=0, microsecond=0)
    if local < cutoff:
        return daily.loc[daily.index.date < local.date()]
    return daily.loc[daily.index.date <= local.date()]


def last_finished_intraday(frame: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Yahoo 15-minute bar timestamps are bar START, not completion time."""
    if frame.empty:
        return frame
    now = now.astimezone(NY)
    finished = frame.loc[frame.index + pd.Timedelta(minutes=15) <= now]
    return finished.between_time("09:30", "15:45")


def last_finished_five_min(frame: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Use only 5-minute candles that have fully closed (ET market hours)."""
    if frame.empty:
        return frame
    now = now.astimezone(NY)
    completed = frame.loc[frame.index + pd.Timedelta(minutes=5) <= now]
    return completed.between_time("09:30", "15:55")


def previous_period_range(frame: pd.DataFrame, now: datetime, *, kind: str) -> dict:
    if frame.empty:
        return {"high": None, "low": None, "period": None}
    date_now = now.astimezone(NY).date()
    if kind == "week":
        anchor = (date_now - timedelta(days=date_now.weekday()))
        subset = frame.loc[frame.index.date < anchor]
        if subset.empty:
            return {"high": None, "low": None, "period": None}
        last = subset.index[-1].date()
        grouping = subset.loc[[x.date().isocalendar()[:2] == last.isocalendar()[:2] for x in subset.index]]
        label = f"{last.isocalendar().year}-W{last.isocalendar().week:02d}"
    else:
        subset = frame.loc[(frame.index.year < date_now.year) |
                           ((frame.index.year == date_now.year) & (frame.index.month < date_now.month))]
        if subset.empty:
            return {"high": None, "low": None, "period": None}
        last = subset.index[-1]
        grouping = subset.loc[(subset.index.year == last.year) & (subset.index.month == last.month)]
        label = f"{last.year:04d}-{last.month:02d}"
    return {"high": safe(grouping["High"].max()), "low": safe(grouping["Low"].min()),
            "period": label}


def hourly_from_quarters(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    # Align four 15-minute periods to 09:30,10:30... market-local time.
    hourly = frame.resample("60min", origin="start_day", offset="30min").agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum",
    })
    counts = frame["Close"].resample("60min", origin="start_day", offset="30min").count()
    return hourly.loc[counts == 4].dropna(subset=["Close"])


def analyze(symbol: str, daily_raw: pd.DataFrame | None,
            intraday_raw: pd.DataFrame | None, *, now: datetime,
            five_min_raw: pd.DataFrame | None = None) -> dict:
    yahoo, display_name, kind = SYMBOLS[symbol]
    daily = completed_daily(clean_bars(daily_raw, intraday=False), now)
    intraday = last_finished_intraday(clean_bars(intraday_raw, intraday=True), now)
    minute5 = last_finished_five_min(clean_bars(five_min_raw, intraday=True), now)
    last_daily = daily.iloc[-1] if not daily.empty else None
    latest_intraday = intraday.iloc[-1] if not intraday.empty else None
    quote_time = intraday.index[-1] if latest_intraday is not None else None
    today = now.astimezone(NY).date()
    same_session = quote_time is not None and quote_time.date() == today
    intraday_age = (now - quote_time.to_pydatetime().astimezone(timezone.utc)).total_seconds()/60 if same_session else None
    is_recent = same_session and intraday_age is not None and 0 <= intraday_age <= 45
    d = technical(daily)
    q5 = technical(minute5, fast=9, slow=21)
    last5 = minute5.index[-1] if not minute5.empty else None
    five_age = ((now - last5.to_pydatetime().astimezone(timezone.utc)).total_seconds() / 60
                if last5 is not None and last5.date() == today else None)
    is_five_recent = bool(
        five_age is not None and 0 <= five_age <= 20
        and symbol in FIVE_MIN_SYMBOLS
    )
    q15 = technical(intraday)
    hour = hourly_from_quarters(intraday)
    q60 = technical(hour, fast=9, slow=21)
    today_bars = intraday.loc[intraday.index.date == today] if not intraday.empty else intraday
    vwap = None
    if not today_bars.empty and today_bars["Volume"].sum() > 0:
        typical = (today_bars["High"] + today_bars["Low"] + today_bars["Close"]) / 3
        vwap = safe((typical*today_bars["Volume"]).sum()/today_bars["Volume"].sum())
    today_spot = safe(latest_intraday["Close"]) if is_recent else None
    previous_close = safe(last_daily["Close"]) if last_daily is not None else None
    session_change = safe(100*(today_spot/previous_close-1)) if today_spot and previous_close else None
    last_daily_date = daily.index[-1].date().isoformat() if not daily.empty else None
    q15_age = round(intraday_age, 1) if intraday_age is not None else None
    levels = {
        "last_completed_session": {
            "high": safe(last_daily["High"]) if last_daily is not None else None,
            "low": safe(last_daily["Low"]) if last_daily is not None else None,
            "date": last_daily_date,
        },
        "previous_week": previous_period_range(daily, now, kind="week"),
        "previous_month": previous_period_range(daily, now, kind="month"),
    }
    # Never display a current 15m/1h direction if intraday bars are stale.
    return {
        "symbol": symbol, "yahoo_symbol": yahoo, "name": display_name, "kind": kind,
        "daily": d,
        "m5": (
            q5 if is_five_recent
            else {**q5, "bias": "STALE" if symbol in FIVE_MIN_SYMBOLS else "UNAVAILABLE"}
        ),
        "m5_source_bar_start": last5.isoformat() if last5 is not None else None,
        "current_m5_confirmed": is_five_recent,
        "last_finished_5m_age_minutes": round(five_age, 1) if five_age is not None else None,
        "m15": q15 if is_recent else {**q15, "bias": "STALE"},
        "h1": q60 if is_recent else {**q60, "bias": "STALE"},
        "last_completed_close": previous_close,
        "last_completed_session_date": last_daily_date,
        "last_finished_intraday_close": today_spot,
        "intraday_source_bar_start": quote_time.isoformat() if quote_time is not None else None,
        "last_finished_intraday_age_minutes": q15_age,
        "current_intraday_bar_confirmed": bool(is_recent),
        "change_from_last_completed_close_pct": session_change,
        "vwap_today": vwap if is_recent and kind == "etf_proxy" else None,
        "levels": levels,
        "quote_execution_eligible": False,
        "research_only": True,
        "source": "Yahoo Finance via yfinance (unofficial, may be delayed)",
    }


def make_report(daily: dict[str, pd.DataFrame],
                intraday: dict[str, pd.DataFrame], *, now: datetime,
                five_min: dict[str, pd.DataFrame] | None = None) -> dict:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    rows = {}
    five_min = five_min or {}
    for symbol in SYMBOLS:
        rows[symbol] = analyze(symbol, daily.get(symbol), intraday.get(symbol), now=now,
                               five_min_raw=five_min.get(symbol))
    valid = sum(bool(x["last_completed_session_date"]) for x in rows.values())
    if not valid:
        raise ValueError("No validated index history; preserve previous report")
    return {
        "schema": "ghazi.index_research.v1",
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "coverage": {"symbols_requested": len(SYMBOLS), "daily_validated": valid,
                     "intraday_current": sum(x["current_intraday_bar_confirmed"] for x in rows.values()),
                     "five_min_current": sum(x["current_m5_confirmed"] for x in rows.values())},
        "data_role": "RESEARCH_ONLY_NOT_LICENSED_EXECUTION",
        "index_options_signal_authority": False,
        "method": "Completed 5m+15m bars; 5m/1H EMA9/21, daily/15m EMA20/50, RSI14, ATR14; previous completed session/week/month levels",
        "symbols": rows,
        "disclaimer": (
            "Yahoo data is unofficial and may be delayed, incomplete or unavailable. "
            "An ETF proxy price is not its associated index level. "
            "No options quotes, OPRA order flow, Gamma dealer inventory or executable signals are claimed."
        ),
    }


def fetch_frames() -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    import yfinance as yf  # Optional at import-time: tests are always offline.
    daily, intraday, five_min = {}, {}, {}
    for symbol, (ticker, _, _) in SYMBOLS.items():
        try:
            daily[symbol] = yf.Ticker(ticker).history(
                period="6mo", interval="1d", auto_adjust=False
            )
        except Exception:
            daily[symbol] = pd.DataFrame()
        try:
            intraday[symbol] = yf.Ticker(ticker).history(
                period="5d", interval="15m", auto_adjust=False, prepost=False
            )
        except Exception:
            intraday[symbol] = pd.DataFrame()
        if symbol in FIVE_MIN_SYMBOLS:
            try:
                five_min[symbol] = yf.Ticker(ticker).history(
                    period="5d", interval="5m", auto_adjust=False, prepost=False
                )
            except Exception:
                five_min[symbol] = pd.DataFrame()
    return daily, intraday, five_min


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--charts-output", type=Path, default=None)
    args = parser.parse_args()
    daily, intraday, five_min = fetch_frames()
    now = datetime.now(timezone.utc)
    result = make_report(daily, intraday, now=now, five_min=five_min)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix+".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temporary.replace(args.output)
    if args.charts_output is not None:
        from scripts.build_index_chart_snapshot import chart_report, write_chart_report
        charts = chart_report(daily, intraday, five_min, now=now)
        write_chart_report(args.charts_output, charts)
        print("GHAZI INDEX OHLC:", charts["coverage"])
    print("GHAZI INDEX RADAR:", result["coverage"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
