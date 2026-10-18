"""Bounded, keyless SEC EDGAR issuer filing pulse (research-only).

Unlike generic headlines, each link is grounded in an official ticker->CIK
association and the issuer's own SEC submissions JSON. A filing's *existence*
is verifiable; its impact on a stock price is NEVER inferred from the form.
Do not scrape EDGAR HTML or exceed SEC fair-access.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FALLBACK_TICKER_MAP = "https://raw.githubusercontent.com/jadchaar/sec-cik-mapper/main/mappings/stocks/ticker_to_cik.json"
SUBMISSIONS_BASE = "https://data.sec.gov/submissions/"
MAX_SYMBOLS = 24
MAX_FILINGS = 70
WATCH_EXTRA = ("RGC", "BNAI", "RKLB", "IONQ", "RGTI", "ASTS", "SOUN")
FORMS = frozenset({
    "8-K", "8-K/A", "6-K", "10-Q", "10-K", "S-1", "S-3",
    "F-3", "424B5", "424B2", "S-4", "SC 13D", "SC 13D/A",
})
TICKER = re.compile(r"[A-Z][A-Z0-9.\-]{0,8}\Z")
DOCUMENT = re.compile(r"[A-Za-z0-9._-]{1,180}\Z")
ACCESSION = re.compile(r"\d{10}-\d{2}-\d{6}\Z")


def symbols_from_brief(brief: dict, limit: int = MAX_SYMBOLS) -> list[str]:
    stocks = brief.get("stocks") if isinstance(brief.get("stocks"), list) else []
    candidates = []
    for row in stocks:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        direction = str(row.get("direction_research") or "")
        volume = row.get("rvol")
        if TICKER.fullmatch(symbol):
            candidates.append((symbol, 1 if direction in {"CALL","UP"} else 0,
                               float(volume) if isinstance(volume,(int,float)) else 0))
    candidates.sort(key=lambda x:(x[1], x[2]),reverse=True)
    result = []
    # Keep compact-capitalization watch symbols even if scanner ranks mega-caps.
    for symbol in (*WATCH_EXTRA, *(x[0] for x in candidates)):
        if symbol not in result and TICKER.fullmatch(symbol):
            result.append(symbol)
        if len(result)>=limit:
            break
    return result


def _get(session: Any, url: str, agent: str) -> dict:
    response = session.get(url,headers={
        "User-Agent":agent,
        "Accept":"application/json",
        "Accept-Encoding":"gzip, deflate",
    },timeout=10)
    response.raise_for_status()
    if len(getattr(response,"content",b""))>5_000_000:
        raise ValueError("SEC response exceeds safe size limit")
    data = response.json()
    if not isinstance(data,dict):
        raise ValueError("malformed SEC JSON")
    return data


def ticker_cik_map(payload: dict) -> dict[str,tuple[int,str]]:
    result={}
    for row in payload.values():
        if not isinstance(row,dict):
            continue
        symbol=str(row.get("ticker") or "").upper().strip()
        try:cik=int(row.get("cik_str"))
        except (ValueError,TypeError):continue
        if TICKER.fullmatch(symbol) and cik>0:
            result[symbol]=(cik,str(row.get("title") or symbol)[:125])
    return result


def mirror_ticker_cik_map(payload: dict) -> dict[str,tuple[int,str]]:
    """Third-party 2025 SEC-derived ticker map, CIK verified on SEC itself.

    This is *not* independent SEC confirmation; use only to nominate a CIK.
    Publication requires that fresh data.sec.gov submissions list the ticker.
    """
    result={}
    for symbol,raw_cik in payload.items():
        ticker=str(symbol).upper().strip()
        try:cik=int(raw_cik)
        except (ValueError,TypeError):continue
        if TICKER.fullmatch(ticker) and cik>0:
            result[ticker]=(cik,ticker)
    return result


def _category(form: str) -> str:
    if form in {"S-1","S-3","F-3","424B5","424B2","S-4"}:
        return "OFFERING_OR_DILUTION_REVIEW"
    if form in {"10-Q","10-K"}:
        return "EARNINGS_OR_PERIODIC_REPORT_REVIEW"
    if form in {"8-K","8-K/A","6-K"}:
        return "MATERIAL_EVENT_REVIEW"
    return "OWNERSHIP_CHANGE_REVIEW"


def parse_submissions(symbol: str, cik: int, issuer: str, payload: dict, *,
                      now: datetime, lookback_days: int=14) -> list[dict]:
    # Detect wrong CIK responses rather than associating documents with
    # similarly named issuers / ticker changes.
    try:
        payload_cik=int(payload.get("cik"))
    except (TypeError,ValueError):
        return []
    if payload_cik!=cik:
        return []
    recent=payload.get("filings",{}).get("recent",{})
    if not isinstance(recent,dict):
        return []
    forms=recent.get("form",[])
    dates=recent.get("filingDate",[])
    accessions=recent.get("accessionNumber",[])
    docs=recent.get("primaryDocument",[])
    if not all(isinstance(x,list) for x in (forms,dates,accessions,docs)):
        return []
    cutoff=now.date()-timedelta(days=max(1,lookback_days))
    rows=[]
    for form,day,acc,doc in zip(forms[:200],dates[:200],accessions[:200],docs[:200]):
        if form not in FORMS or not isinstance(day,str):
            continue
        try:filed=date.fromisoformat(day)
        except ValueError:continue
        if not (cutoff<=filed<=now.date()):
            continue
        if not isinstance(acc,str) or not ACCESSION.fullmatch(acc):
            continue
        if not isinstance(doc,str) or not DOCUMENT.fullmatch(doc) or doc in {".",".."}:
            continue
        url=(f"https://www.sec.gov/Archives/edgar/data/{cik}/"
             f"{acc.replace('-','')}/{doc}")
        rows.append({
            "symbol":symbol,"issuer":issuer,"cik":cik,
            "form":form,"filing_date":filed.isoformat(),
            "accession_number":acc,"source_url":url,
            "source":"SEC EDGAR issuer submissions",
            "event_type":_category(form),
            "original_filing_confirmed":True,
            "issuer_cik_mapping_used":True,
            "positive_price_impact_verified":False,
            "price_direction":"UNKNOWN",
            "research_only":True,
        })
    return rows


def collect(brief: dict, *, now: datetime, session: Any = requests,
            agent: str, pause: Any=time.sleep, max_symbols:int=MAX_SYMBOLS) -> dict:
    if now.tzinfo is None:
        raise ValueError("Timezone-aware now required")
    now=now.astimezone(timezone.utc)
    selected=symbols_from_brief(brief,max_symbols)
    failures={}
    reports=[]
    inspected=0
    map_origin="OFFICIAL_SEC_TICKER_MAP"
    try:
        mapping=ticker_cik_map(_get(session,TICKERS_URL,agent))
    except (requests.RequestException,ValueError,TypeError) as exc:
        mapping={}
        failures["ticker_map"]=getattr(getattr(exc,"response",None),"status_code",None) or type(exc).__name__
    if not mapping:
        # A mirror is a *lookup only* and cannot authenticate a company by
        # itself. All mirrored matches require ticker confirmation by the
        # fresh official SEC issuer JSON before publishing any filing.
        try:
            mapping=mirror_ticker_cik_map(_get(session,FALLBACK_TICKER_MAP,agent))
            map_origin="UNVERIFIED_2025_MIRROR_REQUIRES_SEC_TICKER_CONFIRMATION"
        except (requests.RequestException,ValueError,TypeError) as exc:
            mapping={}
            code=getattr(getattr(exc,"response",None),"status_code",None)
            failures["mirror_ticker_map"]=f"HTTP_{code}" if code else type(exc).__name__
    if mapping:
        for symbol in selected:
            entry=mapping.get(symbol)
            if not entry:
                failures[symbol]="CIK_NOT_FOUND"
                continue
            cik,issuer=entry
            pause(0.4)  # SEC fair access, no multiworker burst, no retries on 429.
            try:
                result=_get(session,f"{SUBMISSIONS_BASE}CIK{cik:010d}.json",agent)
                if int(result.get("cik",-1))!=cik:
                    failures[symbol]="CIK_RESPONSE_MISMATCH"
                    continue
                if map_origin!="OFFICIAL_SEC_TICKER_MAP":
                    declared=result.get("tickers")
                    if (not isinstance(declared,list)
                            or symbol not in {str(x).upper() for x in declared}):
                        failures[symbol]="SEC_ISSUER_TICKER_NOT_CONFIRMED"
                        continue
                    issuer=str(result.get("name") or symbol)[:125]
                inspected+=1
                reports.extend(parse_submissions(symbol,cik,issuer,result,now=now))
            except (requests.RequestException,ValueError,TypeError) as exc:
                status=getattr(getattr(exc,"response",None),"status_code",None)
                failures[symbol]=f"HTTP_{status}" if status else type(exc).__name__
                # Refusal is not an empty filing list.
                if status in (403,429):
                    break
    reports.sort(key=lambda x:(x["filing_date"],x["event_type"]=="MATERIAL_EVENT_REVIEW"),reverse=True)
    deduped={}
    for row in reports:
        key=(row["cik"],row["accession_number"])
        deduped.setdefault(key,row)
    filings=list(deduped.values())[:MAX_FILINGS]
    status=("UNAVAILABLE" if inspected==0 else
            "PARTIAL" if failures else
            "OK" if filings else "NO_RECENT_FILINGS")
    return {
        "schema":"ghazi.sec_issuer_pulse.v1",
        "generated_at":now.isoformat(),
        "status":status,
        "source":"US SEC EDGAR submissions and official ticker-CIK map",
        "coverage":{
            "symbols_requested":len(selected),"issuers_inspected":inspected,
            "filings_verified":len(filings),"errors":failures,
        },
        "ticker_mapping_source":map_origin,
        "ticker_mapping_mirror_snapshot_date":("2025-02-28" if map_origin.startswith("UNVERIFIED") else None),
        "filings":filings,
        "policy":{
            "free_no_api_key":True,
            "primary_document_linked":True,
            "positive_news_inferred":False,
            "dilution_forms_are_risk_not_bullish":True,
            "public_latest_close_redistribution":False,
            "no_execution_signals":True,
        },
    }


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--brief",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--max-symbols",type=int,default=MAX_SYMBOLS)
    args=p.parse_args()
    brief=json.loads(args.brief.read_text(encoding="utf-8"))
    if brief.get("schema")!="ghazi.public_decision.v1":
        raise ValueError("unexpected market research source schema")
    import os
    agent=os.getenv("SEC_USER_AGENT","GHAZI Market Research ghazi-bot@users.noreply.github.com")
    result=collect(brief,now=datetime.now(timezone.utc),agent=agent,
                   max_symbols=max(1,min(30,args.max_symbols)))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(args.output.suffix+".tmp")
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    temp.replace(args.output)
    print("SEC official filing pulse:",result["status"],result["coverage"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())
