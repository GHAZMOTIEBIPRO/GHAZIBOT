from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

USER_AGENT = "GHAZI Market Radar 207104176+GHAZMOTIEBIPRO@users.noreply.github.com"

SOURCES: tuple[dict[str, Any], ...] = (
    {
        "name": "SEC submissions",
        "url": "https://data.sec.gov/submissions/CIK0000320193.json",
        "family": "sec_edgar",
        "authority": "official",
        "role": "identity_and_filings_fallback",
        "method": "GET",
    },
    {
        "name": "SEC Company Facts",
        "url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        "family": "sec_edgar",
        "authority": "official",
        "role": "fundamentals_and_share_history",
        "method": "GET",
    },
    {
        "name": "OCC batch documentation",
        "url": "https://www.theocc.com/market-data/market-data-reports/other-market-data-info/batch-processing/volume-query-batch-processing",
        "family": "occ",
        "authority": "official",
        "role": "options_volume_context_contract",
        "method": "GET",
    },
    {
        "name": "U.S. Treasury yield curve",
        "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve",
        "family": "us_treasury",
        "authority": "official",
        "role": "macro_context",
        "method": "GET",
    },
    {
        "name": "FINRA Reg SHO",
        "url": "https://api.finra.org/data/group/OTCMarket/name/regShoDaily",
        "family": "finra",
        "authority": "official",
        "role": "daily_short_sale_volume_context",
        "method": "POST_FINRA",
    },
    {
        "name": "dhawalc/spx-gamma-levels",
        "url": "https://raw.githubusercontent.com/dhawalc/spx-gamma-levels/main/data/latest.json",
        "family": "github_gamma_research",
        "authority": "open_source_shadow",
        "role": "gamma_cross_validation",
        "method": "GET",
    },
    {
        "name": "Alexduanran/spx-0dte-archive",
        "url": "https://raw.githubusercontent.com/Alexduanran/spx-0dte-archive/main/gex/summary.csv",
        "family": "github_gamma_research",
        "authority": "open_source_shadow",
        "role": "gamma_history_validation",
        "method": "GET",
    },
)


def _request(source: dict[str, Any], timeout: int = 10) -> dict[str, Any]:
    method = str(source.get("method") or "GET")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/csv,text/plain,application/xml,*/*;q=0.1",
    }
    data = None
    if method == "POST_FINRA":
        now = datetime.now(timezone.utc).date()
        start = now - timedelta(days=10)
        body = {
            "limit": 1,
            "fields": [
                "tradeReportDate",
                "securitiesInformationProcessorSymbolIdentifier",
                "shortParQuantity",
                "totalParQuantity",
            ],
            "dateRangeFilters": [
                {
                    "fieldName": "tradeReportDate",
                    "startDate": start.isoformat(),
                    "endDate": now.isoformat(),
                }
            ],
            "compareFilters": [
                {
                    "compareType": "equal",
                    "fieldName": "securitiesInformationProcessorSymbolIdentifier",
                    "fieldValue": "AAPL",
                }
            ],
        }
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        str(source["url"]),
        data=data,
        headers=headers,
        method="POST" if method == "POST_FINRA" else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(250_000)
        status = int(getattr(response, "status", 200) or 200)
        content_type = str(response.headers.get("Content-Type") or "")
    if not payload:
        raise ValueError("empty response")
    return {
        "ok": 200 <= status < 300,
        "status": status,
        "bytes_sampled": len(payload),
        "content_type": content_type,
    }


def check(source: dict[str, Any]) -> dict[str, Any]:
    base = {
        "name": source["name"],
        "family": source["family"],
        "authority": source["authority"],
        "role": source["role"],
        "signal_authority": False,
        "independent_family_key": source["family"],
    }
    try:
        return {**base, **_request(source)}
    except urllib.error.HTTPError as exc:
        return {
            **base,
            "ok": False,
            "status": exc.code,
            "error": f"HTTPError: {exc}",
        }
    except Exception as exc:
        return {
            **base,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def build_health_payload() -> dict[str, Any]:
    results = [check(source) for source in SOURCES]
    official = [row for row in results if row["authority"] == "official"]
    official_ok = [row for row in official if row["ok"]]
    research = [row for row in results if row["authority"] != "official"]
    research_ok = [row for row in research if row["ok"]]

    family_health: dict[str, dict[str, Any]] = {}
    for row in results:
        family = str(row["family"])
        family_health.setdefault(
            family,
            {"sources": 0, "ok_sources": 0, "official": False},
        )
        family_health[family]["sources"] += 1
        family_health[family]["ok_sources"] += int(bool(row["ok"]))
        family_health[family]["official"] = (
            family_health[family]["official"]
            or row["authority"] == "official"
        )

    if not official_ok:
        overall = "degraded"
    elif len(official_ok) < len(official):
        overall = "partial"
    else:
        overall = "healthy"

    return {
        "version": "FREE_DATA_FABRIC_V2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "health_only_never_signal_authority": True,
            "same_family_does_not_increase_source_quorum": True,
            "official_outage_does_not_promote_shadow_source": True,
            "failed_source_fails_closed": True,
        },
        "overall": overall,
        "official_sources_ok": len(official_ok),
        "official_sources_total": len(official),
        "shadow_sources_ok": len(research_ok),
        "shadow_sources_total": len(research),
        "families": family_health,
        "sources": results,
    }


def main() -> int:
    payload = build_health_payload()
    out = Path("public/data/free_data_health.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
