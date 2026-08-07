from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests

from .advanced_signals import enrich_sec_event
from .catalyst_selection import best_catalyst_map as _quality_best_catalyst_map
from .catalysts import SEC_BASE, SEC_FEED, CatalystEvent, _clean_text, _score_text
from . import live_scanners as _live_scanners
from .live_scanners import ResilientCatalystScanner

# PublicStockRadar resolves this module global at runtime; use the quality/freshness-aware selector.
_live_scanners.best_catalyst_map = _quality_best_catalyst_map
from .sec_attention import discover_attention_events
from .sec_efts import _cache_read, discover_sec_fulltext_events

HIGH_VALUE_FORMS = (
    "8-K",
    "6-K",
    "SC 13D",
    "SC 13D/A",
    "SC 13G",
    "SC 13G/A",
    "4",
    "S-1",
    "S-1/A",
    "S-3",
    "S-3/A",
    "F-1",
    "F-3",
    "424B5",
)
STRUCTURED_FULL_FETCH_FORMS = {
    "4",
    "SC 13D",
    "SC 13D/A",
    "SC 13G",
    "SC 13G/A",
    "S-1",
    "S-1/A",
    "S-3",
    "S-3/A",
    "F-1",
    "F-3",
    "424B5",
}
INDEX_HINTS = (
    "item 1.01",
    "item 2.01",
    "item 2.02",
    "item 2.03",
    "item 2.04",
    "item 3.01",
    "item 5.02",
    "item 7.01",
    "item 8.01",
    "ex-99",
    "exhibit 99",
    "merger",
    "acquisition",
    "tender offer",
    "clinical",
    "fda",
    "offering",
    "bankruptcy",
    "delisting",
    "material definitive agreement",
)


class StrictCatalystScanner(ResilientCatalystScanner):
    """Ground official events, cache processed accessions and demote secondary news."""

    def __init__(self, settings, *args, **kwargs):
        super().__init__(settings, *args, **kwargs)
        self._accession_cache_path = Path("data/cache/sec_processed_accessions.json")
        self._incremental_status_path = Path("data/cache/sec_incremental_status.json")
        self._accession_state = self._load_accession_state()
        self._sec_incremental_metrics = {
            "feeds_requested": 0,
            "feed_entries_seen": 0,
            "eligible_entries": 0,
            "cache_hits": 0,
            "index_fetches": 0,
            "document_fetches": 0,
            "prefilter_skips": 0,
            "events_emitted": 0,
        }

    def _load_accession_state(self) -> dict:
        if not self._accession_cache_path.exists():
            return {"version": 1, "events": {}}
        try:
            payload = json.loads(self._accession_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "events": {}}
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), dict):
            return {"version": 1, "events": {}}
        return payload

    @staticmethod
    def _accession_key(url: str, title: str, summary: str) -> str:
        combined = f"{url} {title} {summary}"
        match = re.search(r"(\d{10}-\d{2}-\d{6})", combined)
        if match:
            return match.group(1)
        match = re.search(r"/(\d{18})/", combined)
        if match:
            digits = match.group(1)
            return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"
        return re.sub(r"[^a-z0-9]+", "-", combined.lower()).strip("-")[-160:]

    def _save_incremental_state(self) -> None:
        self._accession_cache_path.parent.mkdir(parents=True, exist_ok=True)
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=90)
        events = self._accession_state.setdefault("events", {})
        pruned: dict[str, dict] = {}
        for key, value in events.items():
            event_payload = value.get("event") if isinstance(value, dict) else None
            event_date = str(
                event_payload.get("event_date")
                if isinstance(event_payload, dict)
                else value.get("processed_at", "")[:10]
                if isinstance(value, dict)
                else ""
            )
            try:
                parsed = datetime.strptime(event_date[:10], "%Y-%m-%d").date()
            except ValueError:
                parsed = date.today()
            if parsed >= cutoff:
                pruned[key] = value
        self._accession_state["events"] = pruned
        self._accession_state["updated_at"] = datetime.now(timezone.utc).isoformat()

        temporary = self._accession_cache_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self._accession_state, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(self._accession_cache_path)

        status = {
            **self._sec_incremental_metrics,
            "processed_accessions": len(pruned),
            "updated_at": self._accession_state["updated_at"],
        }
        status_tmp = self._incremental_status_path.with_suffix(".json.tmp")
        status_tmp.write_text(
            json.dumps(status, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        status_tmp.replace(self._incremental_status_path)

    def _fetch_index(self, filing_url: str) -> str:
        response = self.session.get(filing_url, timeout=18)
        response.raise_for_status()
        self._sec_incremental_metrics["index_fetches"] += 1
        return response.text[:500_000]

    @staticmethod
    def _prefilter(form: str, base_text: str, index_html: str) -> bool:
        if form in STRUCTURED_FULL_FETCH_FORMS:
            return True
        combined = f"{base_text} {_clean_text(index_html[:150_000])}".lower()
        base_score, _, _ = _score_text(combined)
        return base_score != 0 or any(hint in combined for hint in INDEX_HINTS)

    def _fetch_primary_document(self, index_html: str, form: str) -> str:
        candidates = re.findall(r'href=["\']([^"\']+)["\']', index_html, flags=re.I)
        ranked: list[tuple[int, str]] = []
        for href in candidates:
            low = href.lower()
            if "/archives/edgar/data/" not in low:
                continue
            if not any(low.endswith(ext) for ext in (".htm", ".html", ".xml", ".txt")):
                continue
            rank = 0
            if form == "4" and low.endswith(".xml"):
                rank += 30
            if form.startswith("SC 13") and "13" in low:
                rank += 20
            if form.startswith("424B") and "424b" in low:
                rank += 20
            if form.startswith(("S-", "F-")):
                compact_form = form.lower().replace("-", "").replace("/a", "")
                if compact_form in low.replace("-", ""):
                    rank += 16
            if "ex99" in low or "ex-99" in low:
                rank += 12
            if "8-k" in low or "6-k" in low:
                rank += 8
            ranked.append((rank, urljoin(SEC_BASE, href)))

        for _, document_url in sorted(set(ranked), reverse=True)[:3]:
            try:
                time.sleep(0.11)
                response = self.session.get(document_url, timeout=18)
                response.raise_for_status()
                self._sec_incremental_metrics["document_fetches"] += 1
                raw = response.text
                if len(raw) > 100:
                    return raw[:400_000]
            except requests.RequestException:
                continue
        return index_html[:400_000]

    def _cached_event(self, key: str) -> CatalystEvent | None:
        cached = self._accession_state.get("events", {}).get(key)
        if not isinstance(cached, dict):
            return None
        event_payload = cached.get("event")
        if not isinstance(event_payload, dict):
            return None
        try:
            event = CatalystEvent(**{name: event_payload.get(name) for name in CatalystEvent.__dataclass_fields__})
        except TypeError:
            return None
        meta = cached.get("meta") if isinstance(cached.get("meta"), dict) else {}
        self._event_meta[(event.symbol, event.url, event.form)] = meta
        self._sec_incremental_metrics["cache_hits"] += 1
        return event

    def _remember_event(self, key: str, event: CatalystEvent, meta: dict) -> None:
        self._accession_state.setdefault("events", {})[key] = {
            "event": event.__dict__,
            "meta": meta,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _sec_events(
        self,
        allowed_symbols: set[str],
        max_per_form: int = 30,
    ) -> list[CatalystEvent]:
        events: list[CatalystEvent] = []
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        by_cik, _ = self._ticker_map()

        for form in HIGH_VALUE_FORMS:
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
                time.sleep(0.11)
                response = self.session.get(SEC_FEED, params=params, timeout=20)
                response.raise_for_status()
                root = ET.fromstring(response.content)
                self._sec_incremental_metrics["feeds_requested"] += 1
            except Exception:
                continue

            for entry in root.findall("atom:entry", namespace):
                self._sec_incremental_metrics["feed_entries_seen"] += 1
                title = entry.findtext("atom:title", default="", namespaces=namespace)
                summary = entry.findtext("atom:summary", default="", namespaces=namespace)
                updated = entry.findtext("atom:updated", default="", namespaces=namespace)[:10]
                link_element = entry.find("atom:link", namespace)
                filing_url = "" if link_element is None else str(link_element.attrib.get("href", ""))
                cik = self._entry_cik(title, summary)
                direct = by_cik.get(cik) if cik else None

                company_text = re.sub(r"\([^)]*CIK[^)]*\)", " ", title, flags=re.I)
                company_text = re.sub(
                    r"\b(8-K|6-K|SC 13D/A|SC 13D|SC 13G/A|SC 13G|FORM 4|424B5|S-1/A|S-1|S-3/A|S-3|F-1|F-3|4)\b",
                    " ",
                    company_text,
                    flags=re.I,
                )
                if direct and direct[0] in allowed_symbols:
                    symbol, company = direct
                    similarity = 1.0
                else:
                    symbol, similarity = self._match_symbol(company_text, allowed_symbols)
                    company = self.aliases.get(symbol, company_text.strip())
                if not symbol or similarity < 0.24:
                    continue

                self._sec_incremental_metrics["eligible_entries"] += 1
                final_url = urljoin(SEC_BASE, filing_url)
                accession = self._accession_key(final_url, title, summary)
                cached_record = self._accession_state.get("events", {}).get(accession)
                if isinstance(cached_record, dict) and cached_record.get("event") is None:
                    self._sec_incremental_metrics["cache_hits"] += 1
                    self._sec_incremental_metrics["prefilter_skips"] += 1
                    continue
                cached = self._cached_event(accession)
                if cached is not None:
                    events.append(cached)
                    continue

                base_text = f"{title} {summary}"
                index_html = ""
                if final_url:
                    try:
                        index_html = self._fetch_index(final_url)
                    except requests.RequestException:
                        index_html = ""

                if not self._prefilter(form, base_text, index_html):
                    self._sec_incremental_metrics["prefilter_skips"] += 1
                    self._accession_state.setdefault("events", {})[accession] = {
                        "event": None,
                        "meta": {"prefilter_skipped": True},
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                    }
                    continue

                raw_filing = self._fetch_primary_document(index_html, form) if index_html else ""
                clean_filing = _clean_text(raw_filing)
                advanced = enrich_sec_event(form, raw_filing or clean_filing)
                score, category, evidence = _score_text(f"{base_text} {clean_filing}")
                event_value = None
                confidence = 0.72
                purpose = "keyword_event"

                if advanced is not None:
                    score = advanced.score
                    category = advanced.category
                    evidence = advanced.evidence
                    event_value = advanced.event_value
                    confidence = advanced.confidence
                    purpose = advanced.purpose
                elif form in {"SC 13G", "SC 13G/A"}:
                    score = 2
                    category = "Passive ownership filing — not activism by default"
                    evidence = "Schedule 13G"
                    confidence = 0.82
                    purpose = "passive_ownership"
                elif form == "4":
                    continue
                elif form in {"S-1", "S-1/A", "S-3", "S-3/A", "F-1", "F-3", "424B5"} and score == 0:
                    score = -12 if form == "424B5" else -8
                    category = "Capital registration / potential dilution overhang"
                    evidence = form
                    confidence = 0.80
                    purpose = "dilution"
                elif score == 0:
                    continue

                meta = {
                    "event_value": event_value,
                    "confidence": confidence,
                    "purpose": purpose,
                    "accession_number": accession,
                    "classification_method": "structured_or_prefiltered_document",
                }
                self._event_meta[(symbol, final_url, form)] = meta
                event = CatalystEvent(
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
                events.append(event)
                self._remember_event(accession, event, meta)

        self._sec_incremental_metrics["events_emitted"] = len(events)
        self._save_incremental_state()
        return events

    def scan(self, symbols: Iterable[str], lookback_days: int = 7) -> pd.DataFrame:
        symbol_list = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        frame = super().scan(symbol_list, lookback_days=lookback_days)

        fulltext_lookback = max(lookback_days, 30)
        cached_start = datetime.now(timezone.utc).date() - timedelta(days=fulltext_lookback)
        efts_rows = _cache_read(cached_start)
        settings = getattr(self, "settings", None)
        if not efts_rows and settings is not None:
            efts_rows = discover_sec_fulltext_events(
                settings,
                lookback_days=fulltext_lookback,
            )

        precision_rows = []
        if settings is not None:
            precision_rows = discover_attention_events(
                settings,
                lookback_days=fulltext_lookback,
            )

        allowed = set(symbol_list)
        official_rows = [
            row for row in list(efts_rows) + list(precision_rows)
            if str(row.get("symbol", "")).upper() in allowed
        ]
        if official_rows:
            official_frame = pd.DataFrame(official_rows)
            frame = pd.concat([frame, official_frame], ignore_index=True, sort=False)

        if frame.empty:
            for column in ("event_value", "confidence", "purpose", "accession_number"):
                frame[column] = pd.Series(dtype="object")
            return frame

        for column, default in (
            ("event_value", None),
            ("confidence", 0.0),
            ("purpose", ""),
            ("evidence", ""),
            ("category", ""),
            ("event_date", ""),
            ("source", ""),
            ("url", ""),
            ("form", ""),
            ("query_family", ""),
            ("items", None),
            ("accession_number", ""),
        ):
            if column not in frame.columns:
                frame[column] = default

        yahoo = frame["source"].astype(str).str.contains("Yahoo", case=False, na=False)
        positive = yahoo & (pd.to_numeric(frame["score"], errors="coerce") > 0)
        negative = yahoo & (pd.to_numeric(frame["score"], errors="coerce") < 0)
        frame.loc[positive, "score"] = pd.to_numeric(
            frame.loc[positive, "score"], errors="coerce"
        ).clip(upper=8)
        frame.loc[negative, "score"] = pd.to_numeric(
            frame.loc[negative, "score"], errors="coerce"
        ).clip(lower=-12)
        frame.loc[yahoo, "confidence"] = 0.35
        frame.loc[yahoo, "purpose"] = "secondary_news"
        frame.loc[yahoo, "category"] = frame.loc[yahoo, "category"].astype(str).map(
            lambda value: f"Secondary mention — {value}"
        )
        frame.loc[yahoo, "evidence"] = frame.loc[yahoo, "evidence"].astype(str).map(
            lambda value: f"{value}; secondary source — verify SEC/company release"
        )

        fda = frame["source"].astype(str).str.contains("FDA", case=False, na=False)
        frame.loc[fda, "confidence"] = pd.to_numeric(
            frame.loc[fda, "confidence"], errors="coerce"
        ).fillna(0.62).clip(upper=0.72)
        frame.loc[fda & frame["purpose"].astype(str).eq(""), "purpose"] = "fda_record"

        precision = frame["source"].astype(str).str.contains("Precision Full-Text", case=False, na=False)
        frame.loc[precision, "confidence"] = pd.to_numeric(
            frame.loc[precision, "confidence"], errors="coerce"
        ).fillna(0.88).clip(lower=0.80, upper=0.97)

        sec_rows = frame["source"].astype(str).str.contains("SEC", case=False, na=False)
        missing_accession = frame["accession_number"].astype(str).eq("")
        frame.loc[sec_rows & missing_accession, "accession_number"] = frame.loc[
            sec_rows & missing_accession
        ].apply(
            lambda row: self._accession_key(
                str(row.get("url", "")),
                str(row.get("headline", "")),
                str(row.get("evidence", "")),
            ),
            axis=1,
        )
        frame["confidence"] = pd.to_numeric(frame["confidence"], errors="coerce").fillna(0.0)
        frame["score"] = pd.to_numeric(frame["score"], errors="coerce").fillna(0.0)
        frame["source_priority"] = frame["source"].astype(str).map(
            lambda value: 5 if "Precision Full-Text" in value else 4 if "Full-Text" in value else 3 if "SEC" in value else 2 if "FDA" in value else 1
        )
        frame["absolute_score"] = frame["score"].abs()
        frame = frame.sort_values(
            ["event_date", "source_priority", "confidence", "absolute_score"],
            ascending=[False, False, False, False],
        )
        frame = frame.drop_duplicates(
            subset=["symbol", "url", "purpose"],
            keep="first",
        )
        return frame.drop(columns=["source_priority", "absolute_score"]).reset_index(drop=True)
