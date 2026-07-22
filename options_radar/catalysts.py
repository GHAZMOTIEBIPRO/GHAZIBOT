from __future__ import annotations

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import pandas as pd
import requests
import yfinance as yf

from .settings import Settings

LOGGER = logging.getLogger(__name__)
SEC_BASE = "https://www.sec.gov"
SEC_FEED = f"{SEC_BASE}/cgi-bin/browse-edgar"
SEC_TICKERS = f"{SEC_BASE}/files/company_tickers.json"
OPENFDA_DRUGSFDA = "https://api.fda.gov/drug/drugsfda.json"

POSITIVE_PATTERNS: dict[str, tuple[int, str]] = {
    "fda approval": (25, "FDA approval"),
    "approved by the fda": (25, "FDA approval"),
    "breakthrough therapy designation": (22, "FDA breakthrough designation"),
    "clinical hold lifted": (22, "Clinical hold lifted"),
    "met its primary endpoint": (21, "Positive clinical trial"),
    "met the primary endpoint": (21, "Positive clinical trial"),
    "positive topline": (20, "Positive clinical trial"),
    "positive top-line": (20, "Positive clinical trial"),
    "definitive merger agreement": (24, "Merger agreement"),
    "merger agreement": (22, "Merger agreement"),
    "tender offer": (22, "Tender offer"),
    "to acquire": (20, "Acquisition"),
    "acquisition of": (19, "Acquisition"),
    "strategic partnership": (18, "Strategic partnership"),
    "collaboration agreement": (17, "Collaboration agreement"),
    "license agreement": (16, "License agreement"),
    "government contract": (17, "Government contract"),
    "contract award": (16, "Contract award"),
    "share repurchase": (15, "Share repurchase"),
    "stock repurchase": (15, "Share repurchase"),
    "strategic alternatives": (12, "Strategic alternatives"),
    "transactioncode>p<": (18, "Insider open-market purchase"),
}

NEGATIVE_PATTERNS: dict[str, tuple[int, str]] = {
    "registered direct offering": (-25, "Registered direct offering"),
    "public offering": (-23, "Public offering"),
    "at-the-market offering": (-22, "ATM offering"),
    "warrant exercise": (-14, "Warrant exercise"),
    "convertible notes": (-16, "Convertible financing"),
    "reverse stock split": (-18, "Reverse split"),
    "going concern": (-18, "Going concern warning"),
    "delisting notice": (-20, "Delisting notice"),
    "clinical hold": (-20, "Clinical hold"),
    "failed to meet": (-24, "Failed endpoint"),
    "did not meet the primary endpoint": (-24, "Failed endpoint"),
    "termination of the merger agreement": (-22, "Merger terminated"),
    "bankruptcy": (-25, "Bankruptcy"),
    "transactioncode>s<": (-12, "Insider sale"),
}


@dataclass(frozen=True)
class CatalystEvent:
    symbol: str
    company: str
    event_date: str
    category: str
    headline: str
    score: int
    source: str
    form: str
    url: str
    evidence: str


def _clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _score_text(text: str) -> tuple[int, str, str]:
    normalized = text.lower()
    hits: list[tuple[int, str, str]] = []
    for pattern, (score, category) in POSITIVE_PATTERNS.items():
        if pattern in normalized:
            hits.append((score, category, pattern))
    for pattern, (score, category) in NEGATIVE_PATTERNS.items():
        if pattern in normalized:
            hits.append((score, category, pattern))
    if not hits:
        return 0, "Unclassified filing/news", "No high-impact keyword"
    negatives = [hit for hit in hits if hit[0] < 0]
    selected = min(negatives, key=lambda item: item[0]) if negatives else max(hits, key=lambda item: item[0])
    evidence = ", ".join(dict.fromkeys(hit[2] for hit in sorted(hits, reverse=True)[:4]))
    return selected[0], selected[1], evidence


def _normalize_name(value: str) -> set[str]:
    stop = {"inc", "corp", "corporation", "company", "co", "ltd", "limited", "plc", "holdings", "holding", "the", "llc", "group"}
    words = re.findall(r"[a-z0-9]+", value.lower())
    return {word for word in words if len(word) > 2 and word not in stop}


def _name_similarity(left: str, right: str) -> float:
    a, b = _normalize_name(left), _normalize_name(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class CatalystScanner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.sec_user_agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": "www.sec.gov",
        })
        self.cache_dir = Path("data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _ticker_map(self) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
        cache = self.cache_dir / "sec_company_tickers.json"
        payload: dict
        try:
            response = self.session.get(SEC_TICKERS, timeout=20)
            response.raise_for_status()
            payload = response.json()
            cache.write_text(response.text, encoding="utf-8")
        except Exception:
            if not cache.exists():
                raise
            import json
            payload = json.loads(cache.read_text(encoding="utf-8"))
        by_cik: dict[str, tuple[str, str]] = {}
        by_ticker: dict[str, str] = {}
        for item in payload.values():
            cik = str(item.get("cik_str", "")).zfill(10)
            ticker = str(item.get("ticker", "")).upper()
            title = str(item.get("title", ""))
            if cik and ticker:
                by_cik[cik] = (ticker, title)
                by_ticker[ticker] = title
        return by_cik, by_ticker

    def _fetch_filing_text(self, filing_url: str) -> str:
        response = self.session.get(filing_url, timeout=20)
        response.raise_for_status()
        page = response.text
        candidates = re.findall(r'href=["\']([^"\']+)["\']', page, flags=re.I)
        ranked: list[tuple[int, str]] = []
        for href in candidates:
            low = href.lower()
            if "/archives/edgar/data/" not in low:
                continue
            if not any(low.endswith(ext) for ext in (".htm", ".html", ".xml", ".txt")):
                continue
            rank = 0
            if "ex99" in low or "ex-99" in low:
                rank += 8
            if "8-k" in low or "6-k" in low:
                rank += 6
            if low.endswith(".xml"):
                rank += 2
            ranked.append((rank, urljoin(SEC_BASE, href)))
        ranked_urls = [url for _, url in sorted(set(ranked), reverse=True)]
        for document_url in ranked_urls[:3]:
            try:
                time.sleep(0.11)
                doc = self.session.get(document_url, timeout=20)
                doc.raise_for_status()
                raw = doc.text
                markers: list[str] = []
                if re.search(r"<transactionCode>\s*P\s*</transactionCode>", raw, flags=re.I):
                    markers.append("transactioncode>p<")
                if re.search(r"<transactionCode>\s*S\s*</transactionCode>", raw, flags=re.I):
                    markers.append("transactioncode>s<")
                text = (" ".join(markers) + " " + _clean_text(raw)).strip()
                if len(text) > 300:
                    return text[:150_000]
            except requests.RequestException:
                continue
        return _clean_text(page)[:100_000]

    def _sec_events(self, allowed_symbols: set[str], max_per_form: int = 16) -> list[CatalystEvent]:
        by_cik, _ = self._ticker_map()
        events: list[CatalystEvent] = []
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        forms = ("8-K", "6-K", "SC 13D", "SC 13D/A", "4")
        for form in forms:
            params = {
                "action": "getcurrent", "type": form, "company": "", "dateb": "",
                "owner": "include", "start": 0, "count": max_per_form, "output": "atom",
            }
            try:
                response = self.session.get(SEC_FEED, params=params, timeout=25)
                response.raise_for_status()
                root = ET.fromstring(response.content)
            except Exception as exc:
                LOGGER.warning("SEC feed failed for %s: %s", form, exc)
                continue
            for entry in root.findall("atom:entry", namespace):
                title = entry.findtext("atom:title", default="", namespaces=namespace)
                summary = entry.findtext("atom:summary", default="", namespaces=namespace)
                updated = entry.findtext("atom:updated", default="", namespaces=namespace)[:10]
                link_element = entry.find("atom:link", namespace)
                url = "" if link_element is None else str(link_element.attrib.get("href", ""))
                cik_match = re.search(r"\((\d{6,10})\)", title)
                if not cik_match:
                    cik_match = re.search(r"CIK[:=\s]+(\d{6,10})", summary, flags=re.I)
                if not cik_match:
                    continue
                cik = cik_match.group(1).zfill(10)
                ticker, company = by_cik.get(cik, ("", title.split(" - ")[-1]))
                if allowed_symbols and ticker not in allowed_symbols:
                    continue
                base_text = f"{title} {summary}"
                base_score, _, _ = _score_text(base_text)
                filing_text = ""
                if url:
                    try:
                        filing_text = self._fetch_filing_text(url)
                    except requests.RequestException as exc:
                        LOGGER.debug("Filing fetch failed %s: %s", url, exc)
                score, category, evidence = _score_text(f"{base_text} {filing_text}")
                if form.startswith("SC 13D") and score == 0:
                    score, category, evidence = 14, "Activist/strategic investor filing", "Schedule 13D"
                if form == "4" and score == 0:
                    continue
                if score == 0 and base_score == 0:
                    continue
                events.append(CatalystEvent(
                    symbol=ticker, company=company, event_date=updated or date.today().isoformat(),
                    category=category, headline=title, score=score, source="SEC EDGAR",
                    form=form, url=url, evidence=evidence,
                ))
        return events

    def _fda_events(self, allowed_symbols: set[str], company_names: dict[str, str], lookback_days: int) -> list[CatalystEvent]:
        end = date.today()
        start = end - timedelta(days=max(1, lookback_days))
        query = (
            'submissions.submission_status:"AP" AND '
            f'submissions.submission_status_date:[{start:%Y%m%d} TO {end:%Y%m%d}]'
        )
        params: dict[str, str | int] = {"search": query, "limit": 99}
        if self.settings.openfda_api_key:
            params["api_key"] = self.settings.openfda_api_key
        try:
            response = requests.get(OPENFDA_DRUGSFDA, params=params, timeout=25)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            results = response.json().get("results", [])
        except Exception as exc:
            LOGGER.warning("openFDA query failed: %s", exc)
            return []
        events: list[CatalystEvent] = []
        for item in results:
            sponsor = str(item.get("sponsor_name", ""))
            best_symbol, best_similarity = "", 0.0
            for symbol, company in company_names.items():
                similarity = _name_similarity(sponsor, company)
                if similarity > best_similarity:
                    best_symbol, best_similarity = symbol, similarity
            if best_similarity < 0.34 or (allowed_symbols and best_symbol not in allowed_symbols):
                continue
            products = item.get("products") or []
            product_name = "Drug application"
            if products:
                product = products[0]
                ingredients = product.get("active_ingredients") or [{}]
                product_name = str(product.get("brand_name") or ingredients[0].get("name", "Drug application"))
            recent_dates = [
                str(submission.get("submission_status_date", ""))
                for submission in item.get("submissions", [])
                if str(submission.get("submission_status", "")) == "AP"
            ]
            event_date = max(recent_dates, default=end.strftime("%Y%m%d"))
            if len(event_date) == 8:
                event_date = f"{event_date[:4]}-{event_date[4:6]}-{event_date[6:]}"
            events.append(CatalystEvent(
                symbol=best_symbol, company=sponsor, event_date=event_date,
                category="FDA approval record", headline=f"{sponsor}: {product_name} approval record",
                score=24, source="openFDA / Drugs@FDA", form="FDA",
                url="https://www.accessdata.fda.gov/scripts/cder/daf/",
                evidence=f"Approved submission; sponsor match {best_similarity:.0%}",
            ))
        return events

    def _yahoo_news_events(self, symbols: Iterable[str], max_per_symbol: int = 4) -> list[CatalystEvent]:
        events: list[CatalystEvent] = []
        for symbol in symbols:
            try:
                items = yf.Ticker(symbol).news or []
            except Exception as exc:
                LOGGER.debug("Yahoo news failed for %s: %s", symbol, exc)
                continue
            for item in items[:max_per_symbol]:
                content = item.get("content") if isinstance(item, dict) else None
                content = content if isinstance(content, dict) else item
                title = str(content.get("title", ""))
                summary = str(content.get("summary", ""))
                score, category, evidence = _score_text(f"{title} {summary}")
                if score == 0:
                    continue
                canonical = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
                url = canonical.get("url", "") if isinstance(canonical, dict) else str(canonical)
                published = str(content.get("pubDate", ""))[:10] or date.today().isoformat()
                events.append(CatalystEvent(
                    symbol=symbol, company=symbol, event_date=published, category=category,
                    headline=title, score=max(-20, min(18, score)), source="Yahoo Finance News",
                    form="NEWS", url=url, evidence=evidence,
                ))
        return events

    def scan(self, symbols: Iterable[str], lookback_days: int = 7) -> pd.DataFrame:
        allowed = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
        _, company_names = self._ticker_map()
        events: list[CatalystEvent] = []
        events.extend(self._sec_events(allowed))
        events.extend(self._fda_events(allowed, company_names, lookback_days))
        events.extend(self._yahoo_news_events(sorted(allowed)))
        if not events:
            return pd.DataFrame(columns=list(CatalystEvent.__dataclass_fields__))
        frame = pd.DataFrame([event.__dict__ for event in events])
        frame["event_date"] = pd.to_datetime(frame["event_date"], errors="coerce").dt.date.astype(str)
        frame["event_key"] = frame["symbol"].fillna("") + "|" + frame["source"] + "|" + frame["headline"].fillna("")
        return (
            frame.sort_values(["score", "event_date"], ascending=[False, False])
            .drop_duplicates("event_key")
            .drop(columns="event_key")
            .reset_index(drop=True)
        )


def best_catalyst_map(frame: pd.DataFrame) -> dict[str, dict]:
    if frame is None or frame.empty or "symbol" not in frame:
        return {}
    result: dict[str, dict] = {}
    for symbol, group in frame[frame["symbol"].astype(str) != ""].groupby("symbol"):
        ordered = group.sort_values("score", ascending=False)
        positive = ordered[ordered["score"] > 0]
        negative = ordered[ordered["score"] < 0]
        best = positive.iloc[0] if not positive.empty else ordered.iloc[0]
        worst_score = float(negative["score"].min()) if not negative.empty else 0.0
        result[str(symbol).upper()] = {
            "score": float(best["score"]) + worst_score,
            "category": str(best["category"]),
            "headline": str(best["headline"]),
            "url": str(best["url"]),
            "source": str(best["source"]),
            "negative_score": worst_score,
        }
    return result
