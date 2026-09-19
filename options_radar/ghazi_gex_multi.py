"""GHAZI BLACK BOX - reproducible SPX GEX research engine.

Methodology adapted from public research in:
- itsfabtrading/Gex-Multi (Apache-2.0): near-expiry window, 0DTE levels,
  gross-gamma magnet and expected-move framing.
- MitchelTurner/GEX: layered data-quality/signal/entry gating concepts.

This is an original implementation; it does not vendor upstream source files.
The output is research/validation data only until walk-forward promotion.
"""

from __future__ import annotations

import json, math, urllib.request
from datetime import datetime, timezone, date
from typing import Any

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
UA = "GHAZI-Black-Box/1.0"
BUSINESS_DAYS = 262
WINDOW_EXPIRATIONS = 4
STRIKE_LOW = 0.80
STRIKE_HIGH = 1.20
PROFILE_POINTS = 61


def get(url=CBOE_URL, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x):
    return math.exp(-0.5*x*x) / math.sqrt(2.0*math.pi)


def greeks_bs(spot, strike, iv, years, rate=0.0):
    if spot <= 0 or strike <= 0 or iv <= 0 or years <= 0:
        return {"delta": 0.0, "vega": 0.0, "gamma": 0.0, "vanna": 0.0, "charm": 0.0,
                "vomma": 0.0, "zomma": 0.0}
    srt = math.sqrt(years)
    d1 = (math.log(spot/strike) + (rate + 0.5*iv*iv)*years) / (iv*srt)
    d2 = d1 - iv*srt
    pdf = norm_pdf(d1)
    cdf1, cdf2 = norm_cdf(d1), norm_cdf(d2)
    gamma = pdf/(spot*iv*srt)
    vega = spot*pdf*srt
    delta = cdf1
    vanna = vega/spot * (1.0 - d1/(iv*srt))
    charm = -pdf*(2*rate*years-d2*iv*srt)/(2*years*iv*srt)
    vomma = vega*d1*d2/iv
    zomma = gamma*((d1*d2-1)/(iv*iv*years))
    return {"delta": delta, "vega": vega, "gamma": gamma, "vanna": vanna,
            "charm": charm, "vomma": vomma, "zomma": zomma}


def gamma_bs(spot, strike, iv, years):
    if spot <= 0 or strike <= 0 or iv <= 0 or years <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * years) / (iv * math.sqrt(years))
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    return pdf / (spot * iv * math.sqrt(years))


def years_to_expiry(expiry, session_date):
    try:
        d = datetime.strptime(str(expiry)[:10], "%Y-%m-%d").date()
    except Exception:
        return None
    if d < session_date:
        return None
    # Business-day floor prevents the 0DTE ATM singularity from dominating.
    days = 0
    cur = session_date
    while cur < d:
        cur = cur.fromordinal(cur.toordinal() + 1)
        if cur.weekday() < 5:
            days += 1
    return max(days, 1) / BUSINESS_DAYS


def contract_rows(payload):
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("CBOE payload missing data")
    spot = f(data.get("current_price") or data.get("price"))
    opts = data.get("options") or []
    rows = []
    for x in opts:
        sym = str(x.get("option") or "").upper()
        # SPXW is critical for 0DTE. Do not silently discard it.
        if not sym.startswith("SPX"):
            continue
        strike = f(x.get("strike"))
        iv = f(x.get("iv") or x.get("implied_volatility"))
        oi = f(x.get("open_interest"))
        exp = x.get("expiration_date") or x.get("expiration")
        if strike and iv and oi is not None and exp:
            typ = str(x.get("option_type") or x.get("type") or "").lower()
            if typ.startswith("c"):
                typ = "call"
            elif typ.startswith("p"):
                typ = "put"
            else:
                # CBOE option symbol: last character C/P.
                typ = "call" if sym.endswith("C") else ("put" if sym.endswith("P") else "")
            if typ:
                rows.append({"symbol": sym, "strike": strike, "iv": iv / 100 if iv > 1 else iv,
                             "oi": oi, "expiry": str(exp)[:10], "type": typ})
    if spot is None or not rows:
        raise ValueError("No usable SPX option chain")
    return spot, rows


def interpolate_flip(profile):
    for i in range(len(profile) - 1):
        a, b = profile[i], profile[i + 1]
        if a["gex"] == 0:
            return a["strike"]
        if a["gex"] * b["gex"] < 0:
            x1, x2 = a["strike"], b["strike"]
            y1, y2 = a["gex"], b["gex"]
            return x1 + (0 - y1) * (x2 - x1) / (y2 - y1)
    return None


def build(payload=None, session_date=None):
    payload = payload or get()
    spot, rows = contract_rows(payload)
    session_date = session_date or datetime.now(timezone.utc).date()

    expiries = sorted({r["expiry"] for r in rows if years_to_expiry(r["expiry"], session_date) is not None})
    expiries = expiries[:WINDOW_EXPIRATIONS]
    rows = [r for r in rows if r["expiry"] in expiries]
    if not rows:
        raise ValueError("No contracts in expiration window")

    by_strike = {}
    total_abs = 0.0
    for r in rows:
        t = years_to_expiry(r["expiry"], session_date)
        g = gamma_bs(spot, r["strike"], r["iv"], t) * r["oi"] * 100 * spot * spot * 0.01 / 1e9
        signed = g if r["type"] == "call" else -g
        d = by_strike.setdefault(r["strike"], {"call": 0.0, "put": 0.0, "net": 0.0, "oi_call": 0.0, "oi_put": 0.0})
        d[r["type"]] += g
        d["net"] += signed
        d["oi_"+r["type"]] += r["oi"]
        total_abs += abs(g)

    strikes = sorted(by_strike)
    eligible = [k for k in strikes if spot * STRIKE_LOW <= k <= spot * STRIKE_HIGH]
    profile = []
    for level in [spot * STRIKE_LOW + (spot * (STRIKE_HIGH-STRIKE_LOW))*i/(PROFILE_POINTS-1) for i in range(PROFILE_POINTS)]:
        gsum = 0.0
        for r in rows:
            t = years_to_expiry(r["expiry"], session_date)
            g = gamma_bs(level, r["strike"], r["iv"], t) * r["oi"] * 100 * level * level * 0.01 / 1e9
            gsum += g if r["type"] == "call" else -g
        profile.append({"strike": level, "gex": gsum})
    flip = interpolate_flip(profile)

    if not eligible:
        raise ValueError("No strikes around spot")
    call_wall = max(eligible, key=lambda k: by_strike[k]["net"])
    put_wall = min(eligible, key=lambda k: by_strike[k]["net"])
    magnet = max(eligible, key=lambda k: by_strike[k]["call"] + by_strike[k]["put"])
    net_gex = sum(by_strike[k]["net"] for k in eligible)

    front = expiries[0]
    zero = [k for k in eligible if str(front) == str(front)]
    front_map = {}
    for r in rows:
        if r["expiry"] != front: continue
        t = years_to_expiry(r["expiry"], session_date)
        g = gamma_bs(spot, r["strike"], r["iv"], t) * r["oi"] * 100 * spot * spot * 0.01 / 1e9
        d = front_map.setdefault(r["strike"], 0.0)
        front_map[r["strike"]] = d + (g if r["type"] == "call" else -g)
    zdte_call = max(front_map, key=front_map.get) if front_map else None
    zdte_put = min(front_map, key=front_map.get) if front_map else None
    zdte_abs = sum(abs(v) for v in front_map.values())
    zdte_share = zdte_abs / total_abs if total_abs else None

    regime = "positive" if flip is not None and spot > flip else ("negative" if flip is not None else "unknown")

    # Greek exposure profile: OI-weighted signed dealer-style exposure.
    greek_totals = {k: 0.0 for k in ("dex","vanna","charm","vomma","zomma")}
    near_rows = [r for r in rows if abs(r["strike"]-spot)/spot <= 0.03]
    for r in near_rows:
        t = years_to_expiry(r["expiry"], session_date)
        gk = greeks_bs(spot, r["strike"], r["iv"], t)
        sign = 1.0 if r["type"] == "call" else -1.0
        scale = r["oi"] * 100
        greek_totals["dex"] += sign * gk["delta"] * scale
        greek_totals["vanna"] += sign * gk["vanna"] * scale
        greek_totals["charm"] += sign * gk["charm"] * scale
        greek_totals["vomma"] += sign * gk["vomma"] * scale
        greek_totals["zomma"] += sign * gk["zomma"] * scale

    abs_gamma = sum(abs(v) for v in [by_strike[k]["net"] for k in eligible])
    concentration = max((abs(by_strike[k]["net"]) for k in eligible), default=0.0) / abs_gamma if abs_gamma else None
    total_oi_call = sum(v["oi_call"] for v in by_strike.values())
    total_oi_put = sum(v["oi_put"] for v in by_strike.values())
    pc_oi = total_oi_put / total_oi_call if total_oi_call else None

    return {
        "available": True, "engine": "ghazi_gex_multi_reimplementation",
        "methodology_sources": ["itsfabtrading/Gex-Multi", "MitchelTurner/GEX"],
        "policy": "shadow_validation_never_signal_authority",
        "spot": spot, "net_gex": net_gex, "gamma_flip": flip,
        "call_wall": call_wall, "put_wall": put_wall, "magnet": magnet,
        "gamma_regime": regime, "front_expiry": front,
        "expirations_used": len(expiries), "zdte_call_wall": zdte_call,
        "zdte_put_wall": zdte_put, "zdte_share_abs_gex": zdte_share,
        "top_abs_gamma": sorted(
            [{"strike": k, "net_gex": by_strike[k]["net"]} for k in eligible],
            key=lambda x: abs(x["net_gex"]), reverse=True)[:10],
        "data_quality": {
            "contracts": len(rows), "strikes": len(eligible),
            "expirations": len(expiries), "has_spxw": any(r["symbol"].startswith("SPXW") for r in rows),
            "coverage_ok": len(eligible) >= 10 and len(expiries) >= 1,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
