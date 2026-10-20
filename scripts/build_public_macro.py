"""Fetch CFTC index-futures positioning and the Treasury yield curve.

Standard library only. The module is loaded by file path because the
package __init__ imports pandas, which this job does not install.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ghazi_public_macro", ROOT / "options_radar" / "public_macro.py")
macro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(macro)

CFTC_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
                "&field_tdr_date_value={year}&page&_format=csv")
HEADERS = {"User-Agent": "GHAZI-RADAR public-data research (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"}


def _get(url: str, attempts: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except OSError as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{type(last).__name__}: {last}")


def cftc_rows() -> list[dict]:
    codes = ",".join(f"'{spec['code']}'" for spec in macro.INDEX_CONTRACTS.values())
    query = urllib.parse.urlencode({
        "$where": f"cftc_contract_market_code in({codes})",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(len(macro.INDEX_CONTRACTS) * (macro.LOOKBACK_WEEKS + 4)),
    })
    payload = json.loads(_get(f"{CFTC_URL}?{query}"))
    if not isinstance(payload, list):
        raise TypeError("CFTC response is not a list")
    return payload


def treasury_rows(today: datetime) -> list[dict]:
    rows = []
    for year in (today.year - 1, today.year):
        rows.extend(macro.parse_treasury_csv(_get(TREASURY_URL.format(year=year)).decode("utf-8-sig")))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    errors: dict[str, str] = {}
    cot: list[dict] = []
    curve: list[dict] = []
    try:
        cot = cftc_rows()
    except (RuntimeError, TypeError, ValueError) as exc:
        errors["cftc"] = str(exc)[:300]
    try:
        curve = treasury_rows(now)
    except (RuntimeError, ValueError) as exc:
        errors["treasury"] = str(exc)[:300]
    report = macro.build(cot, curve, generated_at=now.isoformat(), errors=errors)
    available = sum(bool(v.get("available")) for v in report["cftc_index_futures"].values())
    if not available and not report["treasury_curve"].get("available"):
        print("Public macro: nothing validated; keeping the previous file.", json.dumps(errors))
        return 1
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(out)
    print("Public macro:", json.dumps({
        "cftc_contracts": {k: (v.get("positions_as_of") or v.get("reason")) for k, v in report["cftc_index_futures"].items()},
        "curve_date": report["treasury_curve"].get("curve_date"),
        "spreads_bp": report["treasury_curve"].get("spreads_bp"),
        "errors": errors,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
