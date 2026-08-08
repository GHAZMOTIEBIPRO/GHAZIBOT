from __future__ import annotations

import json
import math
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yfinance as yf

NASDAQ_SCREENER = "https://api.nasdaq.com/api/screener/stocks"
CACHE_PATH = Path("data/cache/structural_microfloat_candidates.json")
UNIVERSE_PATH = Path("data/universe.txt")
START_MARKER = "# BLACK BOX Ω STRUCTURAL START"
END_MARKER = "# BLACK BOX Ω STRUCTURAL END"
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,6}$")


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _valid_symbol(value: Any) -> bool:
    symbol = str(value or "").strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        return False
    if symbol.endswith(("WS", "WT")):
        return False
    if len(symbol) >= 4 and symbol.endswith(("W", "U", "R")):
        return False
    return symbol not in {"N/A", "NA", "NONE", "NULL", "SYMBOL", "TICKER"}


def _nasdaq_rows() -> list[dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GHAZI-Market-Radar/Structural-Scanner)",
        "Accept": "application/json,text/plain,*/*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/market-activity/stocks/screener",
    }
    response = requests.get(
        NASDAQ_SCREENER,
        params={"tableonly": "true", "limit": "10000", "offset": "0", "download": "true"},
        headers=headers,
        timeout=35,
    )
    response.raise_for_status()
    payload = response.json() or {}
    data = payload.get("data") if isinstance(payload, dict) else {}
    rows = (data or {}).get("rows") if isinstance(data, dict) else []
    return [row for row in (rows or []) if isinstance(row, dict)]


def _proxy_candidates(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        symbol = str(row.get("symbol") or "").upper()
        if not _valid_symbol(symbol):
            continue
        market_cap = _number(row.get("marketCap"))
        volume = _number(row.get("volume"))
        price = _number(row.get("lastsale"))
        pct = _number(row.get("pctchange"))
        country = str(row.get("country") or "").strip().lower()
        if country and country not in {"united states", "usa", "u.s.", "us"}:
            continue
        if price <= 0.35 or price > 250:
            continue
        if market_cap <= 0 or market_cap > 2_000_000_000:
            continue
        if volume > 8_000_000:
            continue
        proxy = 0.0
        if market_cap <= 100_000_000:
            proxy += 45
        elif market_cap <= 300_000_000:
            proxy += 35
        elif market_cap <= 750_000_000:
            proxy += 22
        else:
            proxy += 10
        if volume <= 100_000:
            proxy += 25
        elif volume <= 500_000:
            proxy += 18
        elif volume <= 1_500_000:
            proxy += 10
        if abs(pct) <= 8:
            proxy += 8
        candidates.append(
            {
                "symbol": symbol,
                "proxy_score": proxy,
                "nasdaq_market_cap": market_cap,
                "nasdaq_volume": volume,
                "nasdaq_price": price,
                "nasdaq_pct_change": pct,
            }
        )
    candidates.sort(key=lambda row: (row["proxy_score"], -row["nasdaq_market_cap"]), reverse=True)
    return candidates[:limit]


def _yahoo_profile(row: dict[str, Any]) -> dict[str, Any]:
    symbol = row["symbol"]
    info: dict[str, Any] = {}
    try:
        raw = yf.Ticker(symbol).info
        if isinstance(raw, dict):
            info = raw
    except Exception as exc:
        return {**row, "profile_error": f"{type(exc).__name__}: {exc}"}
    float_shares = _number(info.get("floatShares"))
    shares = _number(info.get("sharesOutstanding"))
    insider = _number(info.get("heldPercentInsiders"))
    if 0 < insider <= 1:
        insider *= 100.0
    avg_volume = _number(info.get("averageVolume"), _number(info.get("averageDailyVolume10Day")))
    market_cap = _number(info.get("marketCap"), row.get("nasdaq_market_cap", 0.0))
    price = _number(info.get("currentPrice"), _number(info.get("regularMarketPrice"), row.get("nasdaq_price", 0.0)))

    score = 0.0
    reasons: list[str] = []
    if float_shares > 0:
        if float_shares <= 3_000_000:
            score += 55
            reasons.append(f"float {float_shares/1_000_000:.2f}M")
        elif float_shares <= 10_000_000:
            score += 47
            reasons.append(f"float {float_shares/1_000_000:.1f}M")
        elif float_shares <= 25_000_000:
            score += 36
            reasons.append(f"float {float_shares/1_000_000:.1f}M")
        elif float_shares <= 50_000_000:
            score += 18
    if insider >= 75:
        score += 30
        reasons.append(f"insider {insider:.0f}%")
    elif insider >= 55:
        score += 22
        reasons.append(f"insider {insider:.0f}%")
    elif insider >= 35:
        score += 12
    if float_shares > 0 and shares > 0:
        ratio = float_shares / shares
        if ratio <= 0.12:
            score += 22
            reasons.append(f"float/outstanding {ratio:.0%}")
        elif ratio <= 0.25:
            score += 14
        elif ratio <= 0.40:
            score += 6
    if avg_volume > 0:
        if avg_volume <= 100_000:
            score += 12
            reasons.append("thin historical volume")
        elif avg_volume <= 500_000:
            score += 8
        elif avg_volume <= 1_500_000:
            score += 4
    if 0 < market_cap <= 300_000_000:
        score += 8
    elif 0 < market_cap <= 750_000_000:
        score += 4

    return {
        **row,
        "structural_score": min(100.0, score),
        "float_shares": float_shares,
        "shares_outstanding": shares,
        "insider_ownership_pct": insider,
        "average_volume": avg_volume,
        "market_cap": market_cap,
        "price": price,
        "reasons": reasons,
    }


def _structural_candidates(rows: list[dict[str, Any]], max_profiles: int, max_output: int) -> list[dict[str, Any]]:
    proxy = _proxy_candidates(rows, max_profiles)
    enriched: list[dict[str, Any]] = []
    workers = max(1, min(int(os.getenv("STRUCTURAL_PROFILE_WORKERS", "5")), 8, len(proxy) or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_yahoo_profile, row): row["symbol"] for row in proxy}
        for future in as_completed(futures):
            try:
                enriched.append(future.result())
            except Exception:
                continue
    qualified = []
    for row in enriched:
        score = _number(row.get("structural_score"))
        float_shares = _number(row.get("float_shares"))
        insider = _number(row.get("insider_ownership_pct"))
        # Require a real supply constraint; low market cap alone is not enough.
        supply_constraint = (0 < float_shares <= 25_000_000) or insider >= 55
        if score >= 55 and supply_constraint:
            qualified.append(row)
    qualified.sort(
        key=lambda row: (
            _number(row.get("structural_score")),
            -_number(row.get("float_shares"), 1e15),
            _number(row.get("insider_ownership_pct")),
        ),
        reverse=True,
    )
    return qualified[:max_output]


def _replace_structural_block(symbols: list[str]) -> bool:
    original = UNIVERSE_PATH.read_text(encoding="utf-8") if UNIVERSE_PATH.exists() else ""
    lines = original.splitlines()
    before: list[str] = []
    after: list[str] = []
    in_block = False
    found_start = False
    found_end = False
    for line in lines:
        if line.strip() == START_MARKER:
            found_start = True
            in_block = True
            continue
        if line.strip() == END_MARKER:
            found_end = True
            in_block = False
            continue
        if in_block:
            continue
        if found_start and not found_end:
            continue
        if found_end:
            after.append(line)
        else:
            before.append(line)
    block = [START_MARKER, *symbols, END_MARKER]
    if found_start and found_end:
        new_lines = before + block + after
    else:
        new_lines = lines + ([""] if lines and lines[-1].strip() else []) + block
    updated = "\n".join(new_lines).rstrip() + "\n"
    if updated == original:
        return False
    UNIVERSE_PATH.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    max_profiles = max(20, min(250, int(os.getenv("STRUCTURAL_MAX_PROFILES", "90"))))
    max_output = max(5, min(100, int(os.getenv("STRUCTURAL_MAX_OUTPUT", "45"))))
    try:
        rows = _nasdaq_rows()
        candidates = _structural_candidates(rows, max_profiles=max_profiles, max_output=max_output)
    except Exception as exc:
        print(f"Structural discovery failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        # Never erase the previous structural block on a provider outage.
        return 0
    symbols = [row["symbol"] for row in candidates]
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "Nasdaq full-market screener + Yahoo profile enrichment",
                "market_rows_seen": len(rows),
                "profiles_requested": max_profiles,
                "qualified": len(candidates),
                "symbols": symbols,
                "candidates": candidates,
                "calibration_archetypes": ["RGC-like broken float", "BNAI-like catalyst + micro-float"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    changed = _replace_structural_block(symbols)
    print(f"Structural discovery: market={len(rows)} qualified={len(candidates)} universe_changed={changed}")
    if symbols:
        print("Top structural symbols:", ", ".join(symbols[:15]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
