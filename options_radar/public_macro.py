"""Index-futures positioning (CFTC) and the Treasury yield curve.

Both inputs are U.S. government publications with no access restriction:
the CFTC Traders in Financial Futures report (futures only) through the
CFTC Public Reporting API, and Treasury's daily par yield curve CSV.
Standard library only, so it runs in dependency-free jobs.

What this is and is not:
- CFTC positions are as of Tuesday and released on Friday; they are weekly
  context about who holds index futures, not a direction signal and not
  dealer options positioning.
- Treasury par yields are derived from indicative bid-side quotes near
  15:30 ET; they describe the rate backdrop, not an equity trigger.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

SCHEMA = "ghazi.public_macro.v1"

# CFTC contract market codes (TFF, futures only) with a name token that
# must appear in the published market name; a mismatch means the code
# no longer points at the contract and the row is refused.
INDEX_CONTRACTS: dict[str, dict[str, Any]] = {
    "ES": {"code": "13874A", "token": "S&P 500", "label_ar": "عقود E-mini S&P 500", "symbols": ["SPX", "SPY", "ES"]},
    "NQ": {"code": "209742", "token": "NASDAQ", "label_ar": "عقود Nasdaq-100 المصغرة", "symbols": ["NDX", "QQQ", "NQ"]},
    "RTY": {"code": "239742", "token": "RUSSELL", "label_ar": "عقود Russell 2000 المصغرة", "symbols": ["RUT", "IWM", "RTY"]},
    "YM": {"code": "124603", "token": "DJIA", "label_ar": "عقود داو جونز ($5)", "symbols": ["DJI", "DIA", "YM"]},
    "VX": {"code": "1170E1", "token": "VIX", "label_ar": "عقود VIX الآجلة", "symbols": ["VIX"]},
}
CATEGORIES = {
    "dealer": ("dealer_positions_long_all", "dealer_positions_short_all"),
    "asset_manager": ("asset_mgr_positions_long", "asset_mgr_positions_short"),
    "leveraged_funds": ("lev_money_positions_long", "lev_money_positions_short"),
}
LOOKBACK_WEEKS = 156
EXTREME_LOW, EXTREME_HIGH = 10.0, 90.0
TENORS = {"3M": "3 Mo", "2Y": "2 Yr", "5Y": "5 Yr", "10Y": "10 Yr", "30Y": "30 Yr"}


def _int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _report_date(value: Any) -> date | None:
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def _percentile_index(values: list[int], current: int) -> float | None:
    """COT index: where the latest net sits between the lookback min and max."""
    low, high = min(values), max(values)
    if high == low:
        return None
    return round((current - low) / (high - low) * 100, 1)


def cot_positioning(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_code: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if isinstance(row, dict):
            by_code.setdefault(str(row.get("cftc_contract_market_code", "")).strip(), []).append(row)
    out: dict[str, Any] = {}
    for key, spec in INDEX_CONTRACTS.items():
        history = []
        for row in by_code.get(spec["code"], []):
            when = _report_date(row.get("report_date_as_yyyy_mm_dd"))
            if when is not None:
                history.append((when, row))
        history.sort(key=lambda item: item[0])
        # One report per Tuesday; a duplicated date keeps the last published row.
        history = list({when: row for when, row in history}.items())[-LOOKBACK_WEEKS:]
        if not history:
            out[key] = {"available": False, "reason": "no CFTC rows for this contract code"}
            continue
        latest_date, latest = history[-1]
        name = str(latest.get("market_and_exchange_names", ""))
        if spec["token"] not in name.upper():
            out[key] = {"available": False, "reason": f"contract code now names '{name[:80]}'"}
            continue
        categories = {}
        for category, (long_key, short_key) in CATEGORIES.items():
            nets = [(_int(r.get(long_key)), _int(r.get(short_key))) for _, r in history]
            series = [lg - sh for lg, sh in nets if lg is not None and sh is not None]
            if len(series) != len(history):
                categories[category] = {"available": False, "reason": "missing long/short fields"}
                continue
            index = _percentile_index(series, series[-1]) if len(series) >= 52 else None
            categories[category] = {
                "net": series[-1],
                "weekly_change": series[-1] - series[-2] if len(series) >= 2 else None,
                "cot_index_3y": index,
                "extreme": (None if index is None else
                            "HIGH" if index >= EXTREME_HIGH else "LOW" if index <= EXTREME_LOW else None),
            }
        out[key] = {
            "available": True,
            "market": name,
            "label_ar": spec["label_ar"],
            "symbols": spec["symbols"],
            "positions_as_of": latest_date.isoformat(),
            "weeks": len(history),
            "open_interest": _int(latest.get("open_interest_all")),
            "categories": categories,
        }
    return out


def _yield(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_treasury_csv(text: str) -> list[dict[str, Any]]:
    rows = []
    for raw in csv.DictReader(io.StringIO(text)):
        try:
            # A calendar date in the CSV, not a timestamp; no timezone applies.
            when = datetime.strptime(str(raw.get("Date", "")).strip(), "%m/%d/%Y").date()  # noqa: DTZ007
        except ValueError:
            continue
        rows.append({"date": when, **{tenor: _yield(raw.get(column, "")) for tenor, column in TENORS.items()}})
    return rows


def treasury_curve(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_date = {row["date"]: row for row in rows if isinstance(row.get("date"), date)}
    ordered = [by_date[d] for d in sorted(by_date)]
    usable = [r for r in ordered if r.get("2Y") is not None and r.get("10Y") is not None]
    if not usable:
        return {"available": False, "reason": "no complete Treasury curve rows"}
    last = usable[-1]

    def spread(row: dict[str, Any], long: str, short: str) -> float | None:
        if row.get(long) is None or row.get(short) is None:
            return None
        return round((row[long] - row[short]) * 100, 1)

    def change(tenor: str, sessions: int) -> float | None:
        if len(usable) <= sessions or usable[-1 - sessions].get(tenor) is None or last.get(tenor) is None:
            return None
        return round((last[tenor] - usable[-1 - sessions][tenor]) * 100, 1)

    s10_2, s10_3m = spread(last, "10Y", "2Y"), spread(last, "10Y", "3M")
    return {
        "available": True,
        "curve_date": last["date"].isoformat(),
        "yields_pct": {tenor: last.get(tenor) for tenor in TENORS},
        "spreads_bp": {"10Y_2Y": s10_2, "10Y_3M": s10_3m},
        "inverted": {"10Y_2Y": None if s10_2 is None else s10_2 < 0,
                     "10Y_3M": None if s10_3m is None else s10_3m < 0},
        "change_bp": {tenor: {"5_sessions": change(tenor, 5), "20_sessions": change(tenor, 20)}
                      for tenor in ("2Y", "10Y")},
        "sessions": len(usable),
    }


def build(cot_rows: list[dict[str, Any]], treasury_rows: list[dict[str, Any]], *, generated_at: str,
          errors: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "cftc_index_futures": cot_positioning(cot_rows),
        "treasury_curve": treasury_curve(treasury_rows),
        "errors": errors or {},
        "sources": {
            "cftc": "CFTC Traders in Financial Futures, futures only (publicreporting.cftc.gov, dataset gpe5-46if)",
            "treasury": "U.S. Treasury daily par yield curve rates (home.treasury.gov)",
        },
        "rights": "U.S. government publications; no automated-access restriction",
        "notes_ar": [
            "مراكز CFTC أسبوعية كما في يوم الثلاثاء وتُنشر يوم الجمعة؛ سياق لمن يحمل العقود وليست إشارة اتجاه.",
            "مؤشر COT يقيس موقع صافي المراكز بين أدنى وأعلى قيمة خلال ثلاث سنوات؛ التطرف ليس توقيتًا للانعكاس.",
            "عائدات الخزانة مشتقة من عروض شراء استرشادية قرب 15:30 بتوقيت نيويورك؛ خلفية للفائدة لا محفّز تداول.",
        ],
        "research_only": True,
        "decision_authority": False,
        "execution_authority": False,
    }
