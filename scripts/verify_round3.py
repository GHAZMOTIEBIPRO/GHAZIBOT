"""Pre-merge real-data check on a runner: the two new builders and the link evidence.

1. build_nasdaq_listed: real fetch of nasdaqlisted.txt (the granted product only) -> counts, flags.
2. build_federal_register_feed: real build -> counts, every linked event, unlinked company names.
3. data/issuer_links.json: each evidence page is fetched and checked for its evidence_check text.
Writes nothing to the repository or bot-state.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/tmp/ghazi-verify")
OUT.mkdir(exist_ok=True)


def run(script: str, out: Path) -> dict:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--output", str(out)],
                       capture_output=True, text=True, timeout=300)
    print(f"== {script}: exit {r.returncode}\n{r.stdout[-1500:]}{r.stderr[-800:]}")
    return json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}


def main() -> int:
    nl = run("build_nasdaq_listed.py", OUT / "nasdaq_listed.json")
    if nl:
        print("file_created_at", nl["file_created_at"], json.dumps(nl["counts"]))
        for f in nl["status_flags"][:12]:
            print("  flag", f["symbol"], f["status"], f["status_en"], "|", f["issuer"])
        samples = {r[0]: r for r in nl["rows"] if r[0] in ("NVDA", "GOOGL", "GOOG", "SOUN", "AAPL", "QQQ")}
        print("  samples", json.dumps(samples, ensure_ascii=False))
    fr = run("build_federal_register_feed.py", OUT / "federal_register.json")
    if fr:
        print("documents", json.dumps(fr["documents_by_agency"]), "counts", json.dumps(fr["counts"]))
        for e in fr["linked"]:
            print("  LINKED", e["date"], e["agency"], e["kind"], "|", e["title"][:110], "->",
                  [(x["name"], x["ticker"], x["relation"]) for x in e["links"]], e["source_url"])
        for e in fr["company_unlinked"][:40]:
            print("  UNLINKED", e["date"], e["agency"], e["kind"], [(u["name"], u["reason"]) for u in e["unmatched"]])
    table = json.loads((ROOT / "data" / "issuer_links.json").read_text(encoding="utf-8"))
    for link in table["links"]:
        time.sleep(1)
        title = link["evidence_url"].rsplit("/", 1)[-1]
        try:
            r = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/html/{title}", timeout=30,
                             headers={"User-Agent": "GHAZI-RADAR-link-review/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"})
            text = r.text if r.ok else ""
        except requests.RequestException as exc:
            text, r = "", type("R", (), {"status_code": type(exc).__name__})()
        found = {t: (t in text) for t in link["evidence_check"]}
        print("  EVIDENCE", link["ticker"], link["relation"], r.status_code, json.dumps(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
