"""Fetch recent FDA drug approvals and recalls from openFDA (CC0).

Standard library only; options_radar/fda_events.py is loaded by file path
because the package __init__ imports pandas.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ghazi_fda_events", ROOT / "options_radar" / "fda_events.py")
fda = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fda)

API = "https://api.fda.gov"
HEADERS = {"User-Agent": "GHAZI-RADAR public-data research (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"}
WINDOW_DAYS = 30
# openFDA's own dataset date per endpoint (meta.last_updated): when the source
# last refreshed, not when an event happened or when we first saw it.
SOURCE_UPDATED: dict[str, str] = {}


def _get(path: str, params: dict[str, str], attempts: int = 3) -> list[dict]:
    url = f"{API}{path}?" + urllib.parse.urlencode(params, safe="[]:+")
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as response:
                payload = json.loads(response.read())
            results = payload.get("results") if isinstance(payload, dict) else None
            meta = payload.get("meta") if isinstance(payload, dict) else None
            if isinstance(meta, dict) and isinstance(meta.get("last_updated"), str):
                SOURCE_UPDATED[path] = meta["last_updated"][:10]
            return results if isinstance(results, list) else []
        except urllib.error.HTTPError as exc:
            if exc.code == 404:  # openFDA answers 404 when nothing matches the search
                return []
            last = exc
        except (OSError, ValueError) as exc:
            last = exc
        time.sleep(2 ** attempt)
    raise RuntimeError(f"{type(last).__name__}: {last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--aliases", default=str(ROOT / "data" / "company_aliases.json"))
    parser.add_argument("--sponsors", default=str(ROOT / "data" / "fda_sponsor_aliases.json"))
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    end = now.date()
    start = end - timedelta(days=WINDOW_DAYS)
    span = f"[{start:%Y%m%d}+TO+{end:%Y%m%d}]"
    sponsors = json.loads(Path(args.sponsors).read_text(encoding="utf-8")).get("aliases", {})
    index = fda.build_name_index(json.loads(Path(args.aliases).read_text(encoding="utf-8")), sponsors)
    errors: dict[str, str] = {}
    approvals: list[dict] = []
    recalls: list[dict] = []
    try:
        rows = _get("/drug/drugsfda.json", {"search": f"submissions.submission_status_date:{span}", "limit": "1000"})
        approvals = fda.approval_events(rows, index, start, end)
    except RuntimeError as exc:
        errors["approvals"] = str(exc)[:300]
    try:
        rows = _get("/drug/enforcement.json", {"search": f"report_date:{span}", "limit": "1000"})
        recalls = fda.recall_events(rows, index)
    except RuntimeError as exc:
        errors["recalls"] = str(exc)[:300]
    if len(errors) == 2:
        print("FDA events: both endpoints failed; keeping the previous file.", json.dumps(errors))
        return 1
    report = fda.build(approvals, recalls, generated_at=now.isoformat(), start=start, end=end, errors=errors)
    report["source_last_updated"] = {"approvals": SOURCE_UPDATED.get("/drug/drugsfda.json"),
                                     "recalls": SOURCE_UPDATED.get("/drug/enforcement.json")}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out)
    print("FDA events:", json.dumps(report["counts"]), "errors:", json.dumps(errors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
