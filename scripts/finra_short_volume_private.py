"""FINRA Reg SHO daily short-sale volume, private context only (credentials + approval required).

FINRA's API terms allow access only with FINRA-issued credentials, and finra.org's terms limit use to
non-commercial personal or professional use. So this adapter:
- makes no request at all unless FINRA_API_AUTOMATION_APPROVED is "true" (the owner's record that a FINRA
  developer account exists and its terms were accepted; it is not FINRA's permission and not a
  substitute for reading its terms) AND FINRA_API_CLIENT_ID / FINRA_API_CLIENT_SECRET are set;
- takes a token from FINRA's OAuth endpoint with those credentials, never anonymously;
- writes only to a path outside the public site and bot-state's public data (refused otherwise).

What the numbers are: short-sale VOLUME reported to FINRA facilities on one day (off-exchange). It is not
short interest (positions), and it says nothing about a squeeze or about direction.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from options_radar.source_permissions import allowed  # shared FINRA gate

SCHEMA = "ghazi.finra_short_volume_private.v1"
TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials"
DATA_URL = "https://api.finra.org/data/group/OTCMarket/name/regShoDaily"
MAX_SYMBOLS = 20
NOTE_AR = ("حجم البيع على المكشوف اليومي المُبلَّغ إلى FINRA (خارج البورصة) ليوم واحد؛ ليس الفائدة المكشوفة "
           "(المراكز)، ولا يدل على عصر مراكز ولا على اتجاه. للاستخدام الخاص فقط.")
# Paths that end up on the public site or in bot-state's published data.
PUBLIC_PARTS = ("runtime/public", "public/", "/public/data", "data/live")


def gate(env: dict[str, str]) -> str:
    # The repository-wide gate (same variable) and this adapter's own reading of it must both agree.
    if (env.get("FINRA_API_AUTOMATION_APPROVED") or "").strip().lower() != "true" or (
            env is os.environ and not allowed("finra_api")):
        return "NOT_APPROVED"
    if not (env.get("FINRA_API_CLIENT_ID") or "").strip() or not (env.get("FINRA_API_CLIENT_SECRET") or "").strip():
        return "CREDENTIALS_MISSING"
    return "READY"


def is_public_path(path: Path) -> bool:
    text = str(path.resolve()).replace("\\", "/") + "/"
    return any(part in text for part in PUBLIC_PARTS)


def summarise(symbol: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pure: one symbol's rows -> the latest trade date's sums, the date kept with them."""
    valid = [r for r in rows if isinstance(r, dict) and r.get("tradeReportDate")]
    if not valid:
        return None
    day = max(str(r["tradeReportDate"]) for r in valid)
    latest = [r for r in valid if str(r["tradeReportDate"]) == day]

    def total(key: str) -> float:
        out = 0.0
        for r in latest:
            try:
                out += float(r.get(key) or 0)
            except (TypeError, ValueError):
                continue
        return out

    short, exempt, volume = total("shortParQuantity"), total("shortExemptParQuantity"), total("totalParQuantity")
    return {"symbol": symbol, "trade_date": day, "short_volume": short, "short_exempt_volume": exempt,
            "reported_volume": volume, "short_volume_share": round(short / volume, 4) if volume > 0 else None,
            "facilities": sorted({str(r.get("reportingFacilityCode") or "") for r in latest} - {""}),
            "rows": len(latest), "measure": "SHORT_SALE_VOLUME_NOT_SHORT_INTEREST", "squeeze_inference": False,
            "direction_inference": False}


def fetch(session: Any, env: dict[str, str], symbols: list[str], now: datetime) -> tuple[str, list[dict[str, Any]]]:
    token = session.post(TOKEN_URL, auth=(env["FINRA_API_CLIENT_ID"], env["FINRA_API_CLIENT_SECRET"]), timeout=30)
    if token.status_code != 200:
        return f"TOKEN_HTTP_{token.status_code}", []
    access = (token.json() or {}).get("access_token")
    if not access:
        return "TOKEN_MISSING_IN_RESPONSE", []
    start = (now - timedelta(days=10)).date().isoformat()
    out = []
    for symbol in symbols[:MAX_SYMBOLS]:
        body = {"limit": 100, "fields": ["tradeReportDate", "securitiesInformationProcessorSymbolIdentifier",
                                         "shortParQuantity", "shortExemptParQuantity", "totalParQuantity",
                                         "reportingFacilityCode"],
                "dateRangeFilters": [{"fieldName": "tradeReportDate", "startDate": start, "endDate": now.date().isoformat()}],
                "compareFilters": [{"compareType": "equal", "fieldName": "securitiesInformationProcessorSymbolIdentifier",
                                    "fieldValue": symbol}]}
        r = session.post(DATA_URL, json=body, timeout=30,
                         headers={"Authorization": f"Bearer {access}", "Accept": "application/json"})
        if r.status_code != 200:
            return f"DATA_HTTP_{r.status_code}", out
        rows = r.json()
        got = summarise(symbol, rows if isinstance(rows, list) else [])
        if got:
            out.append(got)
    return "OK", out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True, help="comma-separated tickers")
    parser.add_argument("--output", type=Path, required=True, help="private path (runner temp); public paths refused")
    args = parser.parse_args()
    if is_public_path(args.output):
        print("REFUSED: output path is public")
        return 2
    env = os.environ
    now = datetime.now(timezone.utc)
    status, rows = gate(env), []
    if status == "READY":
        import requests

        try:
            status, rows = fetch(requests.Session(), env, [s.strip().upper() for s in args.symbols.split(",") if s.strip()], now)
        except (requests.RequestException, ValueError) as exc:
            status = f"FETCH_ERROR ({type(exc).__name__})"
    report = {"schema": SCHEMA, "generated_at": now.isoformat(), "status": status, "symbols": rows,
              "source": "FINRA Reg SHO daily short sale volume (api.finra.org, credentialed)",
              "private_only": True, "public_display": False, "note_ar": NOTE_AR,
              "research_only": True, "decision_authority": False, "execution_authority": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    # The log is public: status and counts only, never values.
    print(json.dumps({"status": status, "symbols": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
