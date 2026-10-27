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
                       capture_output=True, text=True, timeout=300, check=False)
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
        for e in fr["company_unlinked"]:
            if e["agency"] in ("FERC", "NRC"):
                continue
            print("  UNLINKED", e["date"], e["agency"], e["kind"], [(u["name"], u["reason"]) for u in e["unmatched"]],
                  "|", e["title"][:120])
        energy = [e for e in fr["company_unlinked"] if e["agency"] in ("FERC", "NRC")]
        names = sorted({u["name"] for e in energy for u in e["unmatched"]})
        print("  ENERGY_UNLINKED", len(energy), "docs;", len(names), "names:", "; ".join(names)[:3000])
        for e in fr["linked"] + fr["company_unlinked"]:
            if e["kind"] != "FR_PRIORITY_REVIEW_VOUCHER":
                continue
            try:
                meta = requests.get(f"https://www.federalregister.gov/api/v1/documents/{e['document_number']}.json",
                                    params={"fields[]": "raw_text_url"}, timeout=30).json()
                body = " ".join(requests.get(meta["raw_text_url"], timeout=30).text.split())
            except (requests.RequestException, ValueError, KeyError) as exc:
                print("  PRV", e["document_number"], "body unavailable", type(exc).__name__)
                continue
            at = body.lower().find("manufactured by")
            at = at if at >= 0 else body.lower().find("voucher")
            print("  PRV", e["document_number"], e["companies"], "|", body[max(0, at - 200):at + 300])
    table = json.loads((ROOT / "data" / "issuer_links.json").read_text(encoding="utf-8"))
    listed = {r[0]: r[1] for r in nl.get("rows", [])} if nl else {}
    for link in table["links"]:
        title = link["evidence_url"].rsplit("/", 1)[-1]
        status, text = "not tried", ""
        for wait in (2, 8, 20):              # bounded retry on rate limiting
            time.sleep(wait)
            try:
                r = requests.get(f"https://en.wikipedia.org/api/rest_v1/page/html/{title}", timeout=30,
                                 headers={"User-Agent": "GHAZI-RADAR-link-review/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"})
                status, text = r.status_code, (r.text if r.ok else "")
            except requests.RequestException as exc:
                status, text = type(exc).__name__, ""
            if status != 429:
                break
        found = {t: (t in text) for t in link["evidence_check"]}
        in_nasdaq = listed.get(link["ticker"]) if link.get("exchange") == "NASDAQ" else "n/a (not Nasdaq-listed)"
        print("  EVIDENCE", link["ticker"], link["relation"], status, json.dumps(found), "| nasdaqlisted:", in_nasdaq)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
