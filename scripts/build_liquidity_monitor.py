"""Build runtime/public/data/liquidity_monitor.json from DOL ETA 539, New York Fed reference rates and
the OFR Short-term Funding Monitor (keyless federal publishers; rights in data/source_rights.json).

Standard library only; modules are loaded by file path (the package __init__ imports pandas).
Per block, the last good copy is kept when a fetch fails or is refused, and it is marked with the
failure (never presented as fresh). The DOL file (13 MB) is fetched with If-Modified-Since, so an
unchanged file is not downloaded again.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


hf = _load("ghazi_http_fetch", "options_radar/http_fetch.py")
lm = _load("ghazi_liquidity_monitor", "options_radar/liquidity_monitor.py")

AR539 = "https://oui.doleta.gov/unemploy/csv/ar539.csv"
NYFED = "https://markets.newyorkfed.org/api/rates/{kind}/{rate}/last/60.json"
OFR = "https://data.financialresearch.gov/v1/{path}"


def _json(result: Any) -> Any:
    try:
        return json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def claims_block(previous: dict[str, Any], today: Any, fetch: dict[str, Any], fetcher: Any) -> dict[str, Any] | None:
    prev = previous.get("claims") or {}
    r = fetcher(AR539, if_modified_since=prev.get("source_last_modified") if prev.get("available") else None,
                timeout=90)
    fetch["claims"] = r.status()
    if r.outcome == "NOT_MODIFIED":
        # unchanged file: recompute ages against today, keep the values
        prev = {**prev, "age_days": None, "not_modified_since": prev.get("source_last_modified")}
        return None if not prev.get("available") else prev
    if not r.ok:
        return None
    rows, rejected = lm.parse_ar539(r.body.decode("utf-8-sig", errors="replace"))
    return lm.claims(rows, today=today, source_last_modified=r.last_modified, rejected=rejected)


def rates_block(today: Any, fetch: dict[str, Any], fetcher: Any) -> dict[str, Any] | None:
    got = {}
    for kind, rate in (("secured", "sofr"), ("unsecured", "effr")):
        r = fetcher(NYFED.format(kind=kind, rate=rate))
        fetch[f"nyfed_{rate}"] = r.status()
        got[rate] = lm.reference_rates(_json(r)) if r.ok else []
    block = lm.funding_rates(got["sofr"], got["effr"], today=today)
    return block if block.get("available") else None


def repo_block(today: Any, fetch: dict[str, Any], fetcher: Any) -> dict[str, Any] | None:
    series, meta = {}, {}
    for key, mnemonic in lm.OFR_SERIES.items():
        r = fetcher(OFR.format(path=f"series/timeseries?mnemonic={mnemonic}"))
        fetch[f"ofr_{key}"] = r.status()
        series[key] = lm.ofr_series(_json(r)) if r.ok else []
        m = fetcher(OFR.format(path=f"metadata/query?mnemonic={mnemonic}"))
        meta[key] = lm.meta_fields(_json(m)) if m.ok else {}
    block = lm.repo(series, meta, today=today)
    return block if block.get("available") else None


def merge(new: dict[str, Any] | None, previous: dict[str, Any], key: str, status: str, now: str) -> dict[str, Any]:
    if new is not None:
        return {**new, "checked_at": now}
    prev = previous.get(key) or {}
    if prev.get("available"):
        # last good copy, labelled: it is the published value as of its own dates, not a fresh read
        return {**prev, "kept_previous_copy": True, "kept_reason": status, "checked_at": now}
    return {"available": False, "reason": status, "checked_at": now}


def main(argv: list[str] | None = None, fetcher: Any = hf.fetch, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    out = Path(args.output)
    try:
        previous = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    fetch: dict[str, Any] = {}
    today = now.date()
    built = {"claims": claims_block(previous, today, fetch, fetcher),
             "funding_rates": rates_block(today, fetch, fetcher),
             "repo": repo_block(today, fetch, fetcher)}
    status = {"claims": fetch.get("claims"),
              "funding_rates": ",".join(f"{k}={v}" for k, v in fetch.items() if k.startswith("nyfed")),
              "repo": ",".join(f"{k}={v}" for k, v in fetch.items() if k.startswith("ofr"))}
    blocks = {k: merge(v, previous, k, status[k] or "NOT_ATTEMPTED", stamp) for k, v in built.items()}
    if blocks["claims"].get("available") and blocks["claims"].get("week_ending"):
        week = datetime.fromisoformat(blocks["claims"]["week_ending"]).date()
        blocks["claims"]["age_days"] = (today - week).days
        blocks["claims"]["stale"] = blocks["claims"]["age_days"] > lm.CLAIMS_STALE_DAYS
    report = lm.build(blocks, generated_at=stamp, fetch=fetch)
    if not report["available"]:
        print("Liquidity monitor: nothing validated and no previous copy; file not written.", json.dumps(fetch))
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    temp.replace(out)
    c, f, rp = report["claims"], report["funding_rates"], report["repo"]
    print("Liquidity monitor:", json.dumps({
        "fetch": fetch,
        "claims": {k: c.get(k) for k in ("week_ending", "initial_claims", "initial_claims_yoy_pct", "jurisdictions",
                                         "stale", "kept_previous_copy", "source_last_modified")},
        "sofr": (f.get("sofr") or {}).get("rate"), "sofr_date": (f.get("sofr") or {}).get("date"),
        "target_range": f.get("target_range"),
        "tri_party_rate": (rp.get("tri_party_rate") or {}).get("value"),
        "tri_party_date": (rp.get("tri_party_rate") or {}).get("date"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
