"""SEC EDGAR "latest filings" Atom feed: the earliest official signal of an issuer event (8-K, 6-K, offerings).

Source: https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=<FORM>&output=atom - the SEC's own
feed of filings as EDGAR accepts them. Fair access: a declared User-Agent with a contact (SEC_USER_AGENT),
well under 10 requests/second (one request per form type per run). Without SEC_USER_AGENT nothing is fetched.

Times: `published` is EDGAR's acceptance time from the feed entry (the filing's publication on EDGAR);
`first_seen` is when this run read it. Neither is invented: a missing time stays None.
CIK -> ticker: the SEC registrant list kept on bot-state (scripts/build_sec_registry.py), else the
repository's reviewed map; a filer without a listed ticker is kept out (no guessing from names).
8-K item codes are labelled (e.g. 2.02 results, 3.02 unregistered sales = possible dilution, 1.01
material agreement); the label describes the filing type, never its price effect.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FEED = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form}&company=&dateb=&owner=include&start=0&count=100&output=atom"
FORMS = ("8-K", "6-K", "424B5", "S-1", "SC 13D")
REGISTRY_URL = "https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/sec_company_tickers.json"
ATOM = "{http://www.w3.org/2005/Atom}"
TITLE = re.compile(r"^(?P<form>[^ ]+(?: [^ ]+)?) - (?P<name>.+?) \((?P<cik>\d{10})\) \((?P<role>[^)]+)\)$")
ITEMS_AR = {"1.01": "اتفاق جوهري", "1.02": "إنهاء اتفاق جوهري", "2.01": "استحواذ أو تصرف بأصول", "2.02": "نتائج مالية",
            "2.03": "التزام مالي مباشر", "3.01": "إشعار شطب أو عدم امتثال إدراج", "3.02": "بيع أسهم غير مسجلة (تخفيف محتمل)",
            "3.03": "تعديل حقوق المساهمين", "5.02": "تغيير في الإدارة", "5.07": "تصويت المساهمين", "7.01": "إفصاح Reg FD",
            "8.01": "أحداث أخرى"}
FORM_AR = {"424B5": "نشرة طرح (تخفيف محتمل)", "S-1": "تسجيل طرح أسهم", "SC 13D": "حصة ملكية مؤثرة ≥5%",
           "6-K": "إفصاح مُصدر أجنبي", "8-K": "حدث جوهري"}


def parse(atom_xml: str, cik_to_ticker: dict[str, str], now: datetime) -> list[dict[str, Any]]:
    root = ET.fromstring(atom_xml)
    out = []
    for entry in root.findall(f"{ATOM}entry"):
        title = (entry.findtext(f"{ATOM}title") or "").strip()
        m = TITLE.match(title)
        if not m or m.group("role") != "Filer":
            continue  # reporting-owner / subject-company duplicates of the same filing
        cik = m.group("cik")
        ticker = cik_to_ticker.get(cik) or cik_to_ticker.get(cik.lstrip("0"))
        if not ticker:
            continue
        summary = entry.findtext(f"{ATOM}summary") or ""
        items = sorted(set(re.findall(r"Item (\d\.\d\d)", summary)))
        link = entry.find(f"{ATOM}link")
        updated = entry.findtext(f"{ATOM}updated")
        try:
            published = datetime.fromisoformat(updated).astimezone(timezone.utc).isoformat() if updated else None
        except ValueError:
            published = None
        out.append({"symbol": ticker, "cik": cik, "form": m.group("form"), "company": m.group("name"),
                    "items": items, "items_ar": [ITEMS_AR[i] for i in items if i in ITEMS_AR],
                    "form_ar": FORM_AR.get(m.group("form"), m.group("form")),
                    "url": link.get("href") if link is not None else None, "published": published,
                    "first_seen": now.isoformat(), "source": "SEC EDGAR latest filings (official)"})
    return out


def cik_map(registry: Any, fallback_path: Path | None = None) -> dict[str, str]:
    """CIK (10 digits) -> ticker; share classes of one CIK keep the first listed ticker only if unique."""
    out: dict[str, str] = {}
    multi: set[str] = set()
    if isinstance(registry, dict) and registry.get("fields") == ["ticker", "cik", "name", "exchange"]:
        for ticker, cik, _name, _exch in registry.get("rows") or []:
            if cik in out and out[cik] != ticker:
                multi.add(cik)
            out.setdefault(cik, ticker)
    for cik in multi:
        out.pop(cik, None)  # GOOG/GOOGL: one filing, two instruments - not assigned to either
    if fallback_path and fallback_path.exists():
        for ticker, cik in json.loads(fallback_path.read_text()).items():
            if str(cik).zfill(10) not in multi:  # never re-assign a shared-class CIK through the fallback
                out.setdefault(str(cik).zfill(10), ticker)
    return out


def fetch(env: dict[str, str] | None = None, forms: tuple[str, ...] = FORMS, opener=urllib.request.urlopen) -> list[dict]:
    env = dict(os.environ if env is None else env)
    agent = (env.get("SEC_USER_AGENT") or "").strip()
    if "@" not in agent:
        return []  # SEC fair access requires a declared contact; nothing fetched without it
    now = datetime.now(timezone.utc)
    try:
        with opener(urllib.request.Request(REGISTRY_URL), timeout=20) as r:
            registry = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        registry = None
    mapping = cik_map(registry, Path(__file__).resolve().parent.parent / "data" / "sec_cik_map.json")
    events: list[dict] = []
    for form in forms:
        req = urllib.request.Request(FEED.format(form=form.replace(" ", "+")),
                                     headers={"User-Agent": agent, "Accept-Encoding": "identity"})
        try:
            with opener(req, timeout=20) as r:
                events.extend(parse(r.read().decode("utf-8", "replace"), mapping, now))
        except (OSError, ValueError, ET.ParseError):
            continue
    return events
