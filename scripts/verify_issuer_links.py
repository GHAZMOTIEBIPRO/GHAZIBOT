"""Runner check of data/issuer_links.json rows: each evidence page is fetched once and checked
for every evidence_check text. Prints one line per row (ticker, names, found texts); the run id
of a passing check is then recorded by review as evidence_verified_run. Nothing is stored.
"""
from __future__ import annotations

import html
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = "GHAZI-RADAR-issuer-links/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"


def main() -> int:
    table = json.loads((ROOT / "data" / "issuer_links.json").read_text(encoding="utf-8"))
    pages: dict[str, tuple[int, str]] = {}
    for link in table["links"]:
        if isinstance(link.get("evidence_verified_run"), int) and "--all" not in sys.argv:
            continue
        url = link["evidence_url"]
        if url not in pages:
            time.sleep(1)
            try:
                r = requests.get(url, timeout=30, headers={"User-Agent": UA})
                pages[url] = (r.status_code, r.text)
            except requests.RequestException as exc:
                pages[url] = (0, type(exc).__name__)
        status, text = pages[url]
        text = html.unescape(text)          # "Pratt &amp; Whitney" in the page source is "Pratt & Whitney"
        found = {t: t in text for t in link.get("evidence_check", [])}
        print("LINK", json.dumps({"ticker": link["ticker"], "name": link["names"][0], "relation": link["relation"],
                                  "http": status, "found": found, "passed": status == 200 and all(found.values())},
                                 ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
