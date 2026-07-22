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

from .catalysts import (
    SEC_BASE,
    SEC_FEED,
    CatalystEvent,
    CatalystScanner,
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

    def _sec_events(
        self,
        allowed_symbols: set[str],
        max_per_form: int = 24,
    ) -> list[CatalystEvent]:
        events: list[CatalystEvent] = []
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        forms = ("8-K", "6-K", "SC 13D", "SC 13D/A", "4")

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
                company_text = re.sub(r"\b(8-K|6-K|SC 13D/A|SC 13D|FORM 4|4)\b", " ", company_text, flags=re.I)
                symbol, similarity = self._match_symbol(company_text, allowed_symbols)
                if not symbol or similarity < 0.24:
                    continue

                base_text = f"{title} {summary}"
                filing_text = ""
                if filing_url:
                    try:
                        filing_text = self._fetch_filing_text(filing_url)
                    except requests.RequestException as exc:
                        LOGGER.debug("Filing fetch failed %s: %s", filing_url, exc)
                score, category, evidence = _score_text(f"{base_text} {filing_text}")
                if form.startswith("SC 13D") and score == 0:
                    score, category, evidence = 14, "Activist/strategic investor filing", "Schedule 13D"
                if form == "4" and score == 0:
                    continue
                if score == 0:
                    continue

                events.append(
                    CatalystEvent(
                        symbol=symbol,
                        company=self.aliases.get(symbol, company_text.strip()),
                        event_date=updated or date.today().isoformat(),
                        category=category,
                        headline=title,
                        score=score,
                        source="SEC EDGAR",
                        form=form,
                        url=urljoin(SEC_BASE, filing_url),
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


class PublicStockRadar(StockRadar):
    """Return a ranked watchlist even when no stock meets the strong-alert threshold."""

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
                    row = self._score(symbol, technical, history, regime, catalyst_map.get(symbol))
                    row["entry_low"], row["entry_high"] = sorted(
                        (float(row["entry_low"]), float(row["entry_high"]))
                    )
                    row["setup_status"] = (
                        "strong_setup"
                        if row["new_stock_setup"]
                        else "qualified"
                        if float(row["score"]) >= 65
                        else "watchlist"
                    )
                    rows.append(row)
                except Exception as exc:
                    errors[symbol] = str(exc)

        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame[frame["score"] >= minimum_display_score].sort_values(
                ["score", "catalyst_score", "relative_volume"],
                ascending=[False, False, False],
            ).head(top).reset_index(drop=True)
        if output_csv:
            path = Path(output_csv)
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
        return StockScanResult(frame, errors, regime)
