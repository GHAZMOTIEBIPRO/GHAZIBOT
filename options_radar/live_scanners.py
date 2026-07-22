from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, datetime, time as clock_time
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from .advanced_signals import enrich_sec_event
from .catalysts import (
    SEC_BASE,
    SEC_FEED,
    CatalystEvent,
    CatalystScanner,
    _clean_text,
    _name_similarity,
    _normalize_name,
    _score_text,
    best_catalyst_map,
)
from .stocks import StockRadar, StockScanResult

LOGGER = logging.getLogger(__name__)
_GENERIC_NEWS_TOKENS = {
    "global", "technology", "technologies", "platform", "platforms", "group",
    "markets", "market", "systems", "system", "digital", "international", "com",
}


class ResilientCatalystScanner(CatalystScanner):
    """Keep free catalyst sources useful when SEC blocks a shared runner IP."""

    def __init__(self, settings, aliases_path: str | Path = "data/company_aliases.json"):
        super().__init__(settings)
        self.session.headers.pop("Host", None)
        if "@" not in self.session.headers.get("User-Agent", ""):
            self.session.headers["User-Agent"] = (
                "GHAZI Options Radar "
                "207104176+GHAZMOTIEBIPRO@users.noreply.github.com"
            )
        self.session.headers.update(
            {
                "Accept": "application/atom+xml,application/json,text/html;q=0.9,*/*;q=0.8",
                "Connection": "keep-alive",
            }
        )
        self.aliases_path = Path(aliases_path)
        self.aliases = self._load_aliases()
        self._event_meta: dict[tuple[str, str, str], dict] = {}

    def _load_aliases(self) -> dict[str, str]:
        if not self.aliases_path.exists():
            return {}
        import json

        payload = json.loads(self.aliases_path.read_text(encoding="utf-8"))
        return {
            str(symbol).strip().upper(): str(company).strip()
            for symbol, company in payload.items()
            if str(symbol).strip() and str(company).strip()
        }

    def _ticker_map(self) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
        try:
            by_cik, by_ticker = super()._ticker_map()
            by_ticker.update({key: value for key, value in self.aliases.items() if key not in by_ticker})
            return by_cik, by_ticker
        except Exception as exc:
            LOGGER.warning("SEC company ticker map unavailable; using local aliases: %s", exc)
            return {}, dict(self.aliases)

    def _match_symbol(self, raw_company: str, allowed_symbols: set[str]) -> tuple[str, float]:
        best_symbol, best_score = "", 0.0
        normalized_raw = raw_company.lower()
        for symbol in allowed_symbols:
            company = self.aliases.get(symbol, symbol)
            similarity = _name_similarity(raw_company, company)
            if company.lower() in normalized_raw:
                similarity = max(similarity, 0.92)
            if similarity > best_score:
                best_symbol, best_score = symbol, similarity
        return best_symbol, best_score

    @staticmethod
    def _entry_cik(title: str, summary: str) -> str:
        match = re.search(r"\((\d{6,10})\)", title)
        if not match:
            match = re.search(r"CIK[:=\s]+(\d{6,10})", summary, flags=re.I)
        return match.group(1).zfill(10) if match else ""

    def _news_is_relevant(self, symbol: str, text: str) -> bool:
        if re.search(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])", text, flags=re.I):
            return True
        company = self.aliases.get(symbol, symbol)
        company_tokens = _normalize_name(company) - _GENERIC_NEWS_TOKENS
        text_tokens = _normalize_name(text)
        if not company_tokens:
            return False
        overlap = len(company_tokens & text_tokens) / len(company_tokens)
        return overlap >= 0.6

    def _fetch_filing_raw(self, filing_url: str, form: str) -> str:
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
            if form == "4" and low.endswith(".xml"):
                rank += 20
            if form.startswith("SC 13D") and "13d" in low:
                rank += 15
            if form.startswith("424B") and "424b" in low:
                rank += 15
            if form.startswith("S-") and form.lower().replace("-", "") in low.replace("-", ""):
                rank += 12
            if "ex99" in low or "ex-99" in low:
                rank += 8
            if "8-k" in low or "6-k" in low:
                rank += 6
            ranked.append((rank, urljoin(SEC_BASE, href)))
        for _, document_url in sorted(set(ranked), reverse=True)[:4]:
            try:
                time.sleep(0.11)
                doc = self.session.get(document_url, timeout=20)
                doc.raise_for_status()
                if len(doc.text) > 100:
                    return doc.text[:400_000]
            except requests.RequestException:
                continue
        return page[:400_000]

    def _sec_events(
        self,
        allowed_symbols: set[str],
        max_per_form: int = 30,
    ) -> list[CatalystEvent]:
        events: list[CatalystEvent] = []
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        forms = (
            "8-K", "6-K", "SC 13D", "SC 13D/A", "4",
            "S-1", "S-1/A", "S-3", "S-3/A", "424B5",
        )
        by_cik, _ = self._ticker_map()

        for form in forms:
            params = {
                "action": "getcurrent",
                "type": form,
                "company": "",
                "dateb": "",
                "owner": "include",
                "start": 0,
                "count": max_per_form,
                "output": "atom",
            }
            try:
                time.sleep(0.12)
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
                filing_url = "" if link_element is None else str(link_element.attrib.get("href", ""))

                company_text = re.sub(r"\([^)]*CIK[^)]*\)", " ", title, flags=re.I)
                company_text = re.sub(
                    r"\b(8-K|6-K|SC 13D/A|SC 13D|FORM 4|424B5|S-1/A|S-1|S-3/A|S-3|4)\b",
                    " ",
                    company_text,
                    flags=re.I,
                )
                cik = self._entry_cik(title, summary)
                direct = by_cik.get(cik) if cik else None
                if direct and direct[0] in allowed_symbols:
                    symbol, company = direct
                    similarity = 1.0
                else:
                    symbol, similarity = self._match_symbol(company_text, allowed_symbols)
                    company = self.aliases.get(symbol, company_text.strip())
                if not symbol or similarity < 0.24:
                    continue

                base_text = f"{title} {summary}"
                raw_filing = ""
                if filing_url:
                    try:
                        raw_filing = self._fetch_filing_raw(filing_url, form)
                    except requests.RequestException as exc:
                        LOGGER.debug("Filing fetch failed %s: %s", filing_url, exc)
                clean_filing = _clean_text(raw_filing)
                advanced = enrich_sec_event(form, raw_filing or clean_filing)
                score, category, evidence = _score_text(f"{base_text} {clean_filing}")
                event_value = None
                confidence = 0.7
                purpose = "keyword_event"
                if advanced is not None:
                    score = advanced.score
                    category = advanced.category
                    evidence = advanced.evidence
                    event_value = advanced.event_value
                    confidence = advanced.confidence
                    purpose = advanced.purpose
                elif form == "4":
                    continue
                elif score == 0:
                    continue

                final_url = urljoin(SEC_BASE, filing_url)
                self._event_meta[(symbol, final_url, form)] = {
                    "event_value": event_value,
                    "confidence": confidence,
                    "purpose": purpose,
                }
                events.append(
                    CatalystEvent(
                        symbol=symbol,
                        company=company,
                        event_date=updated or date.today().isoformat(),
                        category=category,
                        headline=title,
                        score=score,
                        source="SEC EDGAR",
                        form=form,
                        url=final_url,
                        evidence=f"{evidence}; company match {similarity:.0%}",
                    )
                )
        return events

    def _fda_events(
        self,
        allowed_symbols: set[str],
        company_names: dict[str, str],
        lookback_days: int,
    ) -> list[CatalystEvent]:
        events = super()._fda_events(allowed_symbols, company_names, lookback_days)
        return [
            CatalystEvent(
                symbol=event.symbol,
                company=event.company,
                event_date=event.event_date,
                category="FDA approval record — verify materiality",
                headline=event.headline,
                score=min(event.score, 18),
                source=event.source,
                form=event.form,
                url=event.url,
                evidence=event.evidence,
            )
            for event in events
        ]

    def _yahoo_news_events(
        self,
        symbols: Iterable[str],
        max_per_symbol: int = 4,
    ) -> list[CatalystEvent]:
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
                combined = f"{title} {summary}"
                if not self._news_is_relevant(str(symbol), combined):
                    continue
                score, category, evidence = _score_text(combined)
                if score == 0:
                    continue
                canonical = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
                url = canonical.get("url", "") if isinstance(canonical, dict) else str(canonical)
                published = str(content.get("pubDate", ""))[:10] or date.today().isoformat()
                events.append(
                    CatalystEvent(
                        symbol=str(symbol),
                        company=self.aliases.get(str(symbol), str(symbol)),
                        event_date=published,
                        category=category,
                        headline=title,
                        score=max(-18, min(16, score)),
                        source="Yahoo Finance News",
                        form="NEWS",
                        url=url,
                        evidence=evidence,
                    )
                )
        return events

    def scan(self, symbols: Iterable[str], lookback_days: int = 7) -> pd.DataFrame:
        frame = super().scan(symbols, lookback_days=lookback_days)
        if frame.empty:
            for column in ("event_value", "confidence", "purpose"):
                frame[column] = pd.Series(dtype="object")
            return frame

        def metadata(row: pd.Series) -> dict:
            key = (str(row.get("symbol", "")), str(row.get("url", "")), str(row.get("form", "")))
            meta = self._event_meta.get(key, {})
            if meta:
                return meta
            source = str(row.get("source", ""))
            return {
                "event_value": None,
                "confidence": 0.62 if "FDA" in source else 0.38 if "Yahoo" in source else 0.6,
                "purpose": "fda_record" if "FDA" in source else "secondary_news",
            }

        meta_rows = frame.apply(metadata, axis=1, result_type="expand")
        for column in ("event_value", "confidence", "purpose"):
            frame[column] = meta_rows[column] if column in meta_rows else None
        return frame


class PublicStockRadar(StockRadar):
    """Return a ranked watchlist and a separate rejected-opportunity set."""

    @staticmethod
    def _adjust_relative_volume(technical, history: pd.DataFrame):
        if history is None or history.empty or "Volume" not in history or len(history) < 22:
            return technical
        volume = pd.to_numeric(history["Volume"], errors="coerce")
        now_et = datetime.now(ZoneInfo("America/New_York"))
        last_date = pd.Timestamp(history.index[-1]).date()
        current = float(volume.iloc[-1] or 0)
        prior_average = float(volume.iloc[-21:-1].mean())
        if prior_average <= 0:
            return technical

        adjusted = current / prior_average
        if last_date == now_et.date() and now_et.weekday() < 5:
            session_start = datetime.combine(now_et.date(), clock_time(9, 30), tzinfo=now_et.tzinfo)
            session_end = datetime.combine(now_et.date(), clock_time(16, 0), tzinfo=now_et.tzinfo)
            if session_start <= now_et < session_end:
                elapsed = max((now_et - session_start).total_seconds() / (6.5 * 3600), 0.08)
                adjusted = current / elapsed / prior_average
            elif now_et < session_start and len(volume) >= 23:
                previous = float(volume.iloc[-2] or 0)
                previous_average = float(volume.iloc[-22:-2].mean())
                if previous_average > 0:
                    adjusted = previous / previous_average
        return replace(technical, relative_volume20=max(0.0, min(adjusted, 10.0)))

    def scan(
        self,
        symbols: list[str],
        catalysts: pd.DataFrame | None = None,
        top: int = 15,
        output_csv: str | Path | None = None,
        minimum_display_score: float = 0.0,
    ) -> StockScanResult:
        symbols = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        if not symbols:
            raise ValueError("At least one symbol is required")

        regime = self._market_regime()
        catalyst_map = best_catalyst_map(catalysts if catalysts is not None else pd.DataFrame())
        rows: list[dict] = []
        errors: dict[str, str] = {}
        workers = max(1, min(self.settings.max_workers, len(symbols)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self._technical, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    technical, history = future.result()
                    technical = self._adjust_relative_volume(technical, history)
                    rows.append(self._score(symbol, technical, history, regime, catalyst_map.get(symbol)))
                except Exception as exc:
                    errors[symbol] = str(exc)

        all_frame = pd.DataFrame(rows)
        rejected = pd.DataFrame()
        frame = all_frame
        if not all_frame.empty:
            rejected = all_frame[all_frame["rejection_reason"].astype(str) != ""].copy()
            frame = all_frame[
                (all_frame["score"] >= minimum_display_score)
                & (all_frame["rejection_reason"].astype(str) == "")
            ].sort_values(
                ["score", "catalyst_score", "relative_volume"],
                ascending=[False, False, False],
            ).head(top).reset_index(drop=True)
            rejected = rejected.sort_values("score", ascending=False).head(50).reset_index(drop=True)
        if output_csv:
            path = Path(output_csv)
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
        return StockScanResult(frame, errors, regime, rejected)
