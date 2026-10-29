"""Liquidity and labour-market context from three keyless federal publishers.

- DOL ETA 539 (weekly, by state): initial claims (IC, c3) for the week ending `rptdate` and continued
  weeks claimed (CW, c8) for the reflected week `c2` (field names from the DOL data map, page 41).
  Not seasonally adjusted, so a week is only compared with the same week a year earlier.
- New York Fed reference rates (daily): SOFR and EFFR with their volume-weighted percentiles and the
  FOMC target range. Every presentation carries the New York Fed's required notice.
- OFR Short-term Funding Monitor: tri-party overnight/open repo rate and volume (preliminary vintage),
  and money market funds' overnight/open repo holdings (monthly, revised).

Computation only; no network, no clock. Missing or partial data stays missing: a week whose state
coverage is short of the usual count is reported as incomplete, never summed as if complete.
Each block keeps the publisher's own times (observation date, file Last-Modified or series
last_update) next to our fetch time, so later research can use only what was published by then.
"""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from statistics import mean
from typing import Any

SCHEMA = "ghazi.liquidity_monitor.v1"
HISTORY_WEEKS = 104
COVERAGE_LOOKBACK = 8
CLAIMS_STALE_DAYS = 20      # ETA 539 lands about 11 days after the week it covers
RATES_STALE_DAYS = 6
BAND_PCT = 5.0              # claims band: ±5% on the 4-week average vs a year earlier
NYFED_NOTICE = ("The {name} is subject to the Terms of Use posted at newyorkfed.org. The New York Fed is not "
                "responsible for publication of the {name} by GHAZI RADAR, does not sanction or endorse any "
                "particular republication, and has no liability for your use.")
DTCC_NOTE = ("The Secured Overnight Financing Rate (SOFR) Data and Broad General Collateral Rate (BGCR) Data are "
             "calculated using data provided under a license granted to the New York Fed by DTCC Solutions LLC "
             "(\"Solutions\"), an affiliate of The Depository Trust & Clearing Corporation. Solutions, its "
             "affiliates, and third parties from which they obtained data have no liability for the content of "
             "this material.")
OFR_SERIES = {"tri_party_rate": "REPO-TRI_AR_OO-P", "tri_party_volume": "REPO-TRI_TV_OO-P",
              "mmf_repo_holdings": "MMF-MMF_RP_OO-M"}


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).strip().strip('"')[:10])
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def parse_ar539(text: str) -> tuple[list[dict[str, Any]], int]:
    """Rows with a valid state, week, IC and CW; the count of rejected rows is returned too."""
    rows, rejected = [], 0
    for raw in csv.DictReader(io.StringIO(text)):
        week, reflect = _date(raw.get("rptdate")), _date(raw.get("c2"))
        ic, cw = _int(raw.get("c3")), _int(raw.get("c8"))
        st = str(raw.get("st") or "").strip().strip('"')
        if not st or week is None or ic is None or ic < 0 or (cw is not None and cw < 0):
            rejected += 1
            continue
        rows.append({"st": st, "week": week, "reflect": reflect, "ic": ic, "cw": cw})
    return rows, rejected


def _pct(now: float | None, then: float | None) -> float | None:
    return round((now / then - 1) * 100, 1) if now is not None and then else None


def claims(rows: list[dict[str, Any]], *, today: date, source_last_modified: str | None,
           rejected: int = 0) -> dict[str, Any]:
    weeks: dict[date, dict[str, Any]] = {}
    for r in rows:
        w = weeks.setdefault(r["week"], {"states": set(), "ic": 0, "cw": 0, "cw_states": 0, "reflect": r["reflect"]})
        if r["st"] in w["states"]:
            continue  # one row per state and week; a repeat is not added twice
        w["states"].add(r["st"])
        w["ic"] += r["ic"]
        if r["cw"] is not None:
            w["cw"] += r["cw"]
            w["cw_states"] += 1
    if not weeks:
        return {"available": False, "reason": "NO_ROWS", "rejected_rows": rejected}
    ordered = sorted(weeks)
    expected = max(len(weeks[w]["states"]) for w in ordered[-COVERAGE_LOOKBACK:])

    def complete(w: date) -> bool:
        return w in weeks and len(weeks[w]["states"]) >= expected

    full = [w for w in ordered if complete(w)]
    incomplete = [{"week_ending": w.isoformat(), "states": len(weeks[w]["states"]), "expected": expected}
                  for w in ordered[-COVERAGE_LOOKBACK:] if not complete(w)]
    if not full:
        return {"available": False, "reason": "NO_COMPLETE_WEEK", "incomplete_weeks": incomplete}
    latest = full[-1]
    year_ago = latest - timedelta(days=364)

    def avg4(end: date) -> float | None:
        span = [end - timedelta(days=7 * i) for i in range(4)]
        return round(mean(weeks[w]["ic"] for w in span), 0) if all(complete(w) for w in span) else None

    cur = weeks[latest]
    ago = weeks[year_ago] if complete(year_ago) else None
    cw_full = cur["cw_states"] >= expected
    age = (today - latest).days
    a4, a4_ago = avg4(latest), avg4(year_ago)
    yoy4 = _pct(a4, a4_ago)
    # 52 weeks with the same week a year earlier beside each one (None when that week is incomplete)
    chart = [[w.isoformat(), weeks[w]["ic"],
              weeks[w - timedelta(days=364)]["ic"] if complete(w - timedelta(days=364)) else None]
             for w in full[-52:]]
    return {
        "available": True, "stale": age > CLAIMS_STALE_DAYS, "age_days": age,
        "week_ending": latest.isoformat(), "jurisdictions": len(cur["states"]), "expected_jurisdictions": expected,
        "seasonally_adjusted": False,
        "initial_claims": cur["ic"],
        "initial_claims_year_ago": ago["ic"] if ago else None,
        "initial_claims_yoy_pct": _pct(cur["ic"], ago["ic"] if ago else None),
        "initial_claims_4wk_avg": a4, "initial_claims_4wk_avg_year_ago": a4_ago,
        "initial_claims_4wk_yoy_pct": yoy4,
        # descriptive band, stated rule; a comparison, not a forecast
        "band_4wk_vs_year_ago": None if yoy4 is None else
        "LOWER" if yoy4 <= -BAND_PCT else "HIGHER" if yoy4 >= BAND_PCT else "SIMILAR",
        "band_rule": f"4-week average vs the same 4 weeks a year earlier: within ±{BAND_PCT:g}% is SIMILAR",
        "chart_52w": chart,
        "continued_weeks_claimed": cur["cw"] if cw_full else None,
        "continued_reflect_week": cur["reflect"].isoformat() if cur["reflect"] else None,
        "continued_weeks_claimed_year_ago": (ago["cw"] if ago and ago["cw_states"] >= expected else None),
        "continued_yoy_pct": _pct(cur["cw"] if cw_full else None,
                                  ago["cw"] if ago and ago["cw_states"] >= expected else None),
        "incomplete_weeks": incomplete, "rejected_rows": rejected,
        "source_last_modified": source_last_modified,
        "history": [[w.isoformat(), weeks[w]["ic"]] for w in full[-HISTORY_WEEKS:]],
        "fields": {"initial_claims": "ETA 539 c3 (IC), state UI, summed over jurisdictions",
                   "continued_weeks_claimed": "ETA 539 c8 (CW), for the reflected week c2"},
    }


def reference_rates(payload: Any) -> list[dict[str, Any]]:
    out = []
    for r in (payload or {}).get("refRates") or []:
        d, rate = _date(r.get("effectiveDate")), r.get("percentRate")
        if d is None or not isinstance(rate, int | float):
            continue
        out.append({"date": d.isoformat(), "rate": rate, "p1": r.get("percentPercentile1"),
                    "p99": r.get("percentPercentile99"), "volume_bn": r.get("volumeInBillions"),
                    "target_from": r.get("targetRateFrom"), "target_to": r.get("targetRateTo"),
                    "revised": bool(str(r.get("revisionIndicator") or "").strip())})
    return sorted(out, key=lambda x: x["date"])


def _bp(a: Any, b: Any) -> float | None:
    return round((a - b) * 100, 1) if isinstance(a, int | float) and isinstance(b, int | float) else None


def funding_rates(sofr: list[dict[str, Any]], effr: list[dict[str, Any]], *, today: date) -> dict[str, Any]:
    if not sofr or not effr:
        return {"available": False, "reason": "SOFR_MISSING" if not sofr else "EFFR_MISSING"}
    s, e = sofr[-1], effr[-1]
    # the target range is published with EFFR; use the one for SOFR's own date only
    target = next((x for x in reversed(effr) if x["date"] == s["date"]), None)
    age = (today - date.fromisoformat(s["date"])).days
    top_by_date = {x["date"]: x["target_to"] for x in effr if isinstance(x.get("target_to"), int | float)}
    history = [[x["date"], x["rate"], x["p99"], top_by_date.get(x["date"])] for x in sofr]
    above = [h for h in history if isinstance(h[2], int | float) and isinstance(h[3], int | float) and h[2] > h[3]]
    return {
        "available": True, "stale": age > RATES_STALE_DAYS, "age_days": age,
        "sofr": s, "effr": e, "sofr_minus_effr_bp": _bp(s["rate"], e["rate"]) if s["date"] == e["date"] else None,
        "target_range": [target["target_from"], target["target_to"]] if target else None,
        "sofr_minus_target_top_bp": _bp(s["rate"], target["target_to"]) if target else None,
        "sofr_p99_minus_target_top_bp": _bp(s["p99"], target["target_to"]) if target else None,
        # [date, SOFR, SOFR 99th percentile, target-range top that day]
        "sofr_history": history,
        "window_days": len(history),
        "days_p99_above_target_top": len(above),
        "notice": {"SOFR": NYFED_NOTICE.format(name="SOFR"), "EFFR": NYFED_NOTICE.format(name="EFFR"),
                   "dtcc": DTCC_NOTE},
        "publication_rule": "Published about 08:00 ET on the business day after the effective date; "
                            "same-day revisions possible at about 14:30 ET.",
    }


def ofr_series(payload: Any) -> list[tuple[str, float]]:
    out = []
    for item in payload if isinstance(payload, list) else []:
        if isinstance(item, list) and len(item) == 2 and _date(item[0]) and isinstance(item[1], int | float):
            out.append((str(item[0])[:10], float(item[1])))
    return sorted(out)


def _value_ago(series: list[tuple[str, float]], days: int) -> tuple[str, float] | None:
    target = date.fromisoformat(series[-1][0]) - timedelta(days=days)
    older = [x for x in series if date.fromisoformat(x[0]) <= target]
    return older[-1] if older else None


def repo(series: dict[str, list[tuple[str, float]]], meta: dict[str, dict[str, Any]], *, today: date) -> dict[str, Any]:
    out: dict[str, Any] = {"available": False}
    for key, mnemonic in OFR_SERIES.items():
        s = series.get(key) or []
        m = meta.get(key) or {}
        if not s:
            out[key] = {"available": False, "mnemonic": mnemonic, "reason": "NO_OBSERVATIONS"}
            continue
        monthly = key == "mmf_repo_holdings"
        ago = _value_ago(s, 30 if not monthly else 28)
        age = (today - date.fromisoformat(s[-1][0])).days
        block = {"available": True, "mnemonic": mnemonic, "date": s[-1][0], "value": s[-1][1],
                 "history": [list(x) for x in s[-(24 if monthly else 60):]],
                 "stale": age > (75 if monthly else RATES_STALE_DAYS), "age_days": age,
                 "vintage": m.get("vintage") or m.get("vintage_approach"), "source_last_update": m.get("last_update"),
                 "unit": m.get("unit")}
        if ago:
            block["month_ago"] = {"date": ago[0], "value": ago[1]}
            if key == "tri_party_rate":
                block["change_bp"] = _bp(s[-1][1], ago[1])
            else:
                block["change_pct"] = _pct(s[-1][1], ago[1])
        out[key] = block
        out["available"] = True
    out["note"] = ("Tri-party rates are provided by the OFR for informational purposes only and are not intended "
                   "to be referenced in contracts (OFR series notes).")
    return out


def meta_fields(payload: Any) -> dict[str, Any]:
    p = payload if isinstance(payload, dict) else {}
    desc, sched, unit = p.get("description") or {}, p.get("schedule") or {}, p.get("unit") or {}
    return {"vintage": desc.get("vintage"), "vintage_approach": desc.get("vintage_approach"),
            "last_update": sched.get("last_update"), "unit": unit.get("name"), "name": desc.get("name")}


SOURCES = {
    "claims": {"publisher": "U.S. Department of Labor, ETA 539", "url": "https://oui.doleta.gov/unemploy/csv/ar539.csv",
               "rights": "dol_eta539", "attribution": "Source: U.S. Department of Labor (ETA 539)."},
    "funding_rates": {"publisher": "Federal Reserve Bank of New York",
                      "url": "https://markets.newyorkfed.org/api/rates/", "rights": "nyfed_reference_rates",
                      "attribution": "Source: Federal Reserve Bank of New York."},
    "repo": {"publisher": "Office of Financial Research (U.S. Treasury)",
             "url": "https://data.financialresearch.gov/v1/", "rights": "ofr_stfm",
             "attribution": "Source: Office of Financial Research, Short-term Funding Monitor."},
}


def build(blocks: dict[str, dict[str, Any]], *, generated_at: str, fetch: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"schema": SCHEMA, "generated_at": generated_at, "fetch": fetch,
                           "is_signal": False,
                           "use": "Context for the market summary; descriptive, not a trading signal."}
    for key, block in blocks.items():
        out[key] = {**SOURCES[key], **block}
    out["available"] = any(b.get("available") for b in blocks.values())
    return out
