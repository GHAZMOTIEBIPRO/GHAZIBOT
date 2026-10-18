"""BLS monthly context, not trade quotes or signal authority. One keyless batch/day."""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
SERIES = ("CUUR0000SA0", "CUUR0000SA0L1E", "LNS14000000", "CES0000000001")
MAX_BYTES = 800_000


def fetch_bls_json(opener=urlopen) -> dict:
    req = Request(
        API,
        data=json.dumps({"seriesid": list(SERIES)}).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "User-Agent": "GHAZI-RADAR-public-macro/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"},
        method="POST",
    )
    with opener(req, timeout=18) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("BLS payload too large")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError("BLS API failed or rate-limited; retain prior good data")
    return payload


def parse_series(payload: dict) -> dict[str, list[tuple[str, float]]]:
    root = payload.get("Results")
    if not isinstance(root, dict) or not isinstance(root.get("series"), list):
        raise ValueError("Invalid BLS Results.series")
    result: dict[str, list[tuple[str, float]]] = {}
    for row in root["series"]:
        if not isinstance(row, dict) or row.get("seriesID") not in SERIES:
            continue
        ident = row["seriesID"]
        if ident in result:
            raise ValueError("Duplicate BLS series")
        values = {}
        for item in row.get("data", []):
            if not isinstance(item, dict):
                continue
            year, period = str(item.get("year", "")), str(item.get("period", ""))
            if not re.fullmatch(r"20\d{2}", year) or not re.fullmatch(r"M(0[1-9]|1[0-2])", period):
                continue
            try:
                value = float(item["value"])
            except (TypeError, ValueError, KeyError):
                continue
            if not math.isfinite(value):
                continue
            month = f"{year}-{period[1:]}"
            if month in values and values[month] != value:
                raise ValueError("Conflicting BLS observation")
            values[month] = value
        result[ident] = sorted(values.items(), reverse=True)
    if not all(result.get(series) for series in SERIES):
        raise ValueError("Incomplete BLS series; preserve prior snapshot")
    return result


def yoy(series: list[tuple[str, float]]) -> float | None:
    period, latest = series[0]
    earlier = dict(series).get(f"{int(period[:4])-1}-{period[5:]}")
    return 100 * (latest / earlier - 1) if latest > 0 and earlier and earlier > 0 else None


def payroll_change(series: list[tuple[str, float]]) -> float | None:
    period, latest = series[0]
    y, m = map(int, period.split("-"))
    prior = f"{y if m > 1 else y-1:04d}-{m-1 if m > 1 else 12:02d}"
    older = dict(series).get(prior)
    return latest - older if older is not None else None


def build_snapshot(payload: dict, *, now: datetime | None = None) -> dict:
    when = now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    series = parse_series(payload)
    def metric(id_: str, unit: str, derive=None) -> dict:
        rows = series[id_]
        value = rows[0][1] if derive is None else derive(rows)
        return {"period": rows[0][0], "unit": unit,
                "value": round(value, 3) if value is not None else None}
    return {
        "schema": "ghazi_radar.bls_macro.v1",
        "generated_at": when.astimezone(timezone.utc).isoformat(),
        "source": "U.S. Bureau of Labor Statistics",
        "source_url": API,
        "source_family": "bls_official",
        "authority": "OFFICIAL_MACRO_CONTEXT_ONLY",
        "is_realtime": False,
        "may_trigger_call_put": False,
        "indicators": {
            "cpi_yoy_pct": metric("CUUR0000SA0", "%", yoy),
            "core_cpi_yoy_pct": metric("CUUR0000SA0L1E", "%", yoy),
            "unemployment_pct": metric("LNS14000000", "%"),
            "payroll_change_thousands": metric("CES0000000001", "thousands", payroll_change),
        },
        "notes": [
            "CPI YoY from unadjusted indices for the same month of the preceding year.",
            "Unemployment and nonfarm payrolls are seasonally adjusted monthly series.",
            "Payroll change derives from revised monthly level data, not a live release headline.",
            "Observation month is not market quote time or economic release timestamp.",
            "BLS.gov cannot vouch for data or analysis after retrieval from BLS.gov.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = build_snapshot(fetch_bls_json())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(args.output)
    print("Published BLS monthly context snapshot", snapshot["generated_at"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
