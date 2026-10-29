"""Probe of keyless liquidity / macro sources from the runner: OFR Short-term Funding Monitor,
New York Fed reference rates and operations, Federal Reserve Data Download (H.15), and the
Department of Labor weekly claims data. For each: the publisher's terms clauses and robots.txt,
then the data itself - HTTP status, structure, record count, latest observation date and the
publication/vintage fields the source exposes (to avoid look-ahead). Prints only; nothing is
stored, published or sent."""
from __future__ import annotations

import csv
import io
import json
import re
import time
from datetime import UTC, datetime
from typing import Any

import requests
from probe_terms import KEYWORDS, text_of

UA = {"User-Agent": "GHAZI-RADAR-macro-probe/1.0 (github.com/GHAZMOTIEBIPRO/GHAZIBOT)"}
TERMS = {
    "ofr_terms": "https://www.financialresearch.gov/terms-of-use/",
    "ofr_stfm_about": "https://www.financialresearch.gov/short-term-funding-monitor/about/",
    "ofr_api_docs": "https://www.financialresearch.gov/short-term-funding-monitor/api/",
    "ofr_robots": "https://data.financialresearch.gov/robots.txt",
    "nyfed_terms": "https://www.newyorkfed.org/termsofuse",
    "nyfed_reference_rates_terms": "https://www.newyorkfed.org/markets/reference-rates/additional-information-about-reference-rates",
    "nyfed_robots": "https://markets.newyorkfed.org/robots.txt",
    "fed_disclaimer": "https://www.federalreserve.gov/disclaimer.htm",
    "fed_ddp_about": "https://www.federalreserve.gov/datadownload/",
    "fed_robots": "https://www.federalreserve.gov/robots.txt",
    "dol_disclaimer": "https://www.dol.gov/general/disclaim",
    "dol_claims_page": "https://oui.doleta.gov/unemploy/claims.asp",
    "doleta_robots": "https://oui.doleta.gov/robots.txt",
}
MAX_LINES = 30


def get(url: str, **kw: Any) -> tuple[requests.Response | None, float, str]:
    t0 = time.monotonic()
    try:
        r = requests.get(url, headers=UA, timeout=40, **kw)
        return r, round(time.monotonic() - t0, 2), ""
    except requests.RequestException as exc:
        return None, round(time.monotonic() - t0, 2), type(exc).__name__


def terms() -> None:
    for name, url in TERMS.items():
        r, sec, err = get(url)
        print(f"\n===== TERMS {name} | {url}")
        if r is None:
            print(f"FETCH_ERROR {err} after {sec}s")
            continue
        print(f"status={r.status_code} bytes={len(r.content)} final_url={r.url[:120]}")
        if r.status_code != 200:
            continue
        if url.endswith("robots.txt"):
            print(r.text[:1500])
            continue
        lines = [ln.strip() for ln in re.split(r"\n|(?<=[.;])\s{2,}", text_of(r.text)) if len(ln.strip()) > 40]
        for ln in [ln for ln in lines if KEYWORDS.search(ln)][:MAX_LINES]:
            print("-", ln[:600])


def report(name: str, url: str, r: requests.Response | None, sec: float, err: str, **facts: Any) -> None:
    out = {"source": name, "url": url, "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
           "seconds": sec, "http": r.status_code if r is not None else err,
           "content_type": (r.headers.get("Content-Type", "")[:40] if r is not None else None),
           "last_modified": (r.headers.get("Last-Modified") if r is not None else None)}
    out.update(facts)
    print("DATA", json.dumps(out, default=str), flush=True)


def ofr() -> None:
    base = "https://data.financialresearch.gov/v1"
    url = f"{base}/series/dataset"
    r, sec, err = get(url)
    names = sorted(r.json().keys()) if r is not None and r.status_code == 200 else []
    report("ofr_datasets", url, r, sec, err, datasets=names)
    for ds in ("fnyr", "repo", "mmf", "nypd", "tyld"):
        url = f"{base}/metadata/mnemonics?dataset={ds}"
        r, sec, err = get(url)
        rows = r.json() if r is not None and r.status_code == 200 else []
        report(f"ofr_mnemonics_{ds}", url, r, sec, err, count=len(rows) if isinstance(rows, list) else None,
               sample=rows[:4] if isinstance(rows, list) else str(rows)[:300])
    for mnemonic in ("FNYR-SOFR-A", "REPO-TRI_AR_OO-P", "MMF-MMF_RP_OO-M", "NYPD-PD_RP_T_TOT-A"):
        url = f"{base}/metadata/query?mnemonic={mnemonic}"
        r, sec, err = get(url)
        meta = r.json() if r is not None and r.status_code == 200 else {}
        report(f"ofr_meta_{mnemonic}", url, r, sec, err, metadata=str(meta)[:1500])
        url = f"{base}/series/timeseries?mnemonic={mnemonic}"
        r, sec, err = get(url)
        obs = r.json() if r is not None and r.status_code == 200 else []
        obs = obs if isinstance(obs, list) else []
        report(f"ofr_series_{mnemonic}", url, r, sec, err, observations=len(obs),
               first=obs[:1], last=obs[-3:])
        time.sleep(1)


def nyfed() -> None:
    for name, url in (("nyfed_sofr", "https://markets.newyorkfed.org/api/rates/secured/sofr/last/5.json"),
                      ("nyfed_effr", "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/5.json"),
                      ("nyfed_rrp", "https://markets.newyorkfed.org/api/rp/reverserepo/propositions/results/last/5.json")):
        r, sec, err = get(url)
        body = r.json() if r is not None and r.status_code == 200 else {}
        report(name, url, r, sec, err, keys=list(body)[:5], body=json.dumps(body)[:1500])


def fed_ddp() -> None:
    # H.15 Selected Interest Rates, the Board's own CSV output (last 10 observations).
    url = ("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H15&series=bf17364827e38702b42a58cf8eaa3f78"
           "&lastobs=10&from=&to=&filetype=csv&label=include&layout=seriescolumn&type=package")
    r, sec, err = get(url)
    rows = list(csv.reader(io.StringIO(r.text))) if r is not None and r.status_code == 200 else []
    report("fed_ddp_h15", url, r, sec, err, rows=len(rows), header_rows=[row[:6] for row in rows[:6]],
           last_rows=[row[:6] for row in rows[-2:]], columns=len(rows[0]) if rows else 0)


def dol() -> None:
    url = "https://oui.doleta.gov/unemploy/csv/ar539.csv"
    r, sec, err = get(url, stream=True)
    head, tail, n = [], [], 0
    if r is not None and r.status_code == 200:
        for i, line in enumerate(r.iter_lines(decode_unicode=True)):
            n = i + 1
            if i < 3:
                head.append(line[:300])
            tail = ([*tail, line[:300]])[-3:]
            if n > 400000:
                break
    report("dol_ar539", url, r, sec, err, lines=n, head=head, tail=tail,
           bytes_header=r.headers.get("Content-Length") if r is not None else None)
    url = "https://www.dol.gov/ui/data.pdf"
    r, sec, err = get(url)
    report("dol_weekly_release_pdf", url, r, sec, err, bytes=len(r.content) if r is not None else 0)


LINK = re.compile(r'href="([^"]+)"[^>]*>([^<]{0,120})<', re.IGNORECASE)


def links(name: str, url: str, pattern: str) -> None:
    r, sec, err = get(url)
    found = []
    if r is not None and r.status_code == 200:
        found = [(h, t.strip()) for h, t in LINK.findall(r.text) if re.search(pattern, h + " " + t, re.IGNORECASE)]
    report(name, url, r, sec, err, links=list(dict.fromkeys(found))[:40])


def followup() -> None:
    # Where each publisher states its terms, and the definitions of the series a builder would use.
    links("ofr_policy_links", "https://www.financialresearch.gov/short-term-funding-monitor/api/",
          r"polic|terms|disclaim|legal|copyright|privacy")
    links("ofr_home_policy_links", "https://www.financialresearch.gov/", r"polic|terms|disclaim|legal|copyright")
    links("nyfed_policy_links", "https://www.newyorkfed.org/markets/reference-rates/sofr", r"terms|legal|disclaim|use")
    for cand in ("https://www.newyorkfed.org/markets/reference-rates/terms-of-use",
                 "https://www.newyorkfed.org/privacy/termsofuse", "https://www.newyorkfed.org/terms-of-use"):
        r, sec, err = get(cand)
        lines = []
        if r is not None and r.status_code == 200 and "errors/404" not in r.url:
            body = [ln.strip() for ln in re.split(r"\n|(?<=[.;])\s{2,}", text_of(r.text)) if len(ln.strip()) > 40]
            lines = [ln[:600] for ln in body if KEYWORDS.search(ln)][:25]
        report("nyfed_terms_candidate", cand, r, sec, err, final_url=r.url if r is not None else None, lines=lines)
    for mnemonic in ("REPO-TRI_AR_OO-P", "REPO-TRI_TV_OO-P", "MMF-MMF_RP_OO-M"):
        r, sec, err = get(f"https://data.financialresearch.gov/v1/metadata/query?mnemonic={mnemonic}")
        report(f"ofr_full_meta_{mnemonic}", r.url if r is not None else "", r, sec, err,
               metadata=(r.text[:4000] if r is not None else None))
    for rel in ("H41", "H8"):
        links(f"fed_ddp_choose_{rel}", f"https://www.federalreserve.gov/datadownload/Choose.aspx?rel={rel}",
              r"Output\.aspx|series=|Build\.aspx|Preview")
    links("dol_downloads", "https://oui.doleta.gov/unemploy/DataDownloads.asp", r"539|claims|map|csv|pdf")
    links("dol_claims_page_links", "https://oui.doleta.gov/unemploy/claims.asp", r"539|csv|map|definition|pdf")


def section(name: str, url: str, start: str, chars: int = 6000, occurrence: int = 1) -> None:
    """Print the page text from the first occurrence of `start` (whole restriction lists, not keyword lines)."""
    r, sec, err = get(url)
    text = ""
    if r is not None and r.status_code == 200:
        if "pdf" in r.headers.get("Content-Type", "") or url.split("#")[0].endswith(".pdf"):
            from probe_terms import pdf_text
            body = pdf_text(r.content)
        else:
            body = text_of(r.text)
        body = re.sub(r"\s*\n\s*", "\n", body)
        i = -1
        for _ in range(occurrence):
            i = body.find(start, i + 1)
            if i < 0:
                break
        text = body[i:i + chars] if i >= 0 else f"START_NOT_FOUND; first chars: {body[:800]}"
    report(name, url, r, sec, err, text=text)


def restrictions() -> None:
    section("nyfed_use_restrictions", "https://www.newyorkfed.org/privacy/termsofuse", "subject to Use Restrictions", 9000)
    section("ofr_policies", "https://www.financialresearch.gov/about/policies/", "Policies", 5000)
    section("ofr_legal_notices", "https://www.financialresearch.gov/legal-notices/", "Legal", 6000)


def eta539_map() -> None:
    # The DOL data map is a long handbook PDF; the first match is its table of contents, the
    # second is the ETA 539 field list (page 41).
    url = "https://oui.doleta.gov/dmstree/handbooks/402/402_4/4024c6/4024c6.pdf"
    r, sec, err = get(url)
    pages: list[str] = []
    if r is not None and r.status_code == 200:
        from pypdf import PdfReader
        for number, page in enumerate(PdfReader(io.BytesIO(r.content)).pages, start=1):
            text = page.extract_text() or ""
            if "539" in text and re.search(r"\bc2[0-3]\b|rptdate", text):
                pages.append(f"[page {number}] " + re.sub(r"\s*\n\s*", "\n", text)[:5000])
    report("dol_eta539_map", url, r, sec, err, pages=pages[:3])


STEPS = {"terms": terms, "ofr": ofr, "nyfed": nyfed, "fed_ddp": fed_ddp, "dol": dol, "followup": followup,
         "restrictions": restrictions, "eta539_map": eta539_map}


def main() -> int:
    import sys
    chosen = sys.argv[1:] or list(STEPS)
    for step in (STEPS[name] for name in chosen):
        try:
            step()
        except (ValueError, KeyError, TypeError) as exc:
            print("STEP_ERROR", step.__name__, type(exc).__name__, str(exc)[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
