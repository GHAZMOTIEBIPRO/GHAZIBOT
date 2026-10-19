"""Offline SEC CIK identity and filings source verification for free public radar."""
from datetime import datetime, timezone
from types import SimpleNamespace

import requests

from scripts.build_sec_filing_pulse import (
    SUBMISSIONS_BASE, TICKERS_URL, FALLBACK_TICKER_MAP, collect, parse_submissions,
    symbols_from_brief, ticker_cik_map,
)

NOW=datetime(2026,10,18,12,tzinfo=timezone.utc)


def report(cik,forms,dates=None,docs=None,items=None):
    n=len(forms)
    return {
        "cik":cik,
        "filings":{"recent":{
            "form":forms,
            "filingDate":dates or ["2026-10-16"]*n,
            "accessionNumber":[f"0000000001-26-{i+1:06d}" for i in range(n)],
            "primaryDocument":docs or [f"document{i}.htm" for i in range(n)],
            "items":items if items is not None else [""]*n,
        }},
    }


class Response:
    content=b'{}'
    def __init__(self,payload):
        self.payload=payload
    def raise_for_status(self):
        return None
    def json(self):
        return self.payload


class Session:
    def __init__(self, replies):
        self.replies=replies
        self.calls=[]
    def get(self,url,*,headers=None,timeout=None):
        self.calls.append((url,headers,timeout))
        p=self.replies[url]
        if isinstance(p,Exception):
            raise p
        return Response(p)


def test_official_issuer_filing_identity_and_dilution_warning():
    mapping={"0":{"ticker":"RGC","cik_str":111,"title":"Regencell"},
             "1":{"ticker":"BNAI","cik_str":222,"title":"Brand Engagement Network"}}
    session=Session({
        TICKERS_URL:mapping,
        f"{SUBMISSIONS_BASE}CIK0000000111.json":report(111,["8-K","S-3"]),
        f"{SUBMISSIONS_BASE}CIK0000000222.json":report(222,["10-Q"]),
    })
    out=collect({"stocks":[]},now=NOW,session=session,
                agent="Research test@example.com",pause=lambda _:None,max_symbols=2)
    assert out["status"]=="OK"
    assert out["coverage"]["issuers_inspected"]==2
    assert out["coverage"]["filings_verified"]==3
    assert all(x["original_filing_confirmed"] is True for x in out["filings"])
    assert all(x["positive_price_impact_verified"] is False for x in out["filings"])
    assert all(x["price_direction"]=="UNKNOWN" for x in out["filings"])
    offering=next(x for x in out["filings"] if x["form"]=="S-3")
    assert offering["event_type"]=="OFFERING_OR_DILUTION_REVIEW"
    assert "/Archives/edgar/data/111/" in offering["source_url"]
    assert all(v[1]["User-Agent"]=="Research test@example.com" for v in session.calls)


def test_cik_mismatch_and_path_traversal_do_not_emit_filings():
    forged=report(111,["8-K","10-K","8-K"])
    forged["filings"]["recent"]["primaryDocument"]=["../bad","ok.htm","sub/path.htm"]
    assert parse_submissions("RGC",999,"Unrelated",forged,now=NOW)==[]
    got=parse_submissions("RGC",111,"Real Company",forged,now=NOW)
    assert len(got)==1
    assert got[0]["form"]=="10-K"
    assert got[0]["issuer_cik_mapping_used"] is True


def test_unknown_or_malformed_ticker_map_fails_closed():
    assert ticker_cik_map({"0":{"ticker":"AVGO","cik_str":"nan"}})=={}
    assert "RGC" in symbols_from_brief({"stocks":[
        {"symbol":"AAPL","direction_research":"UP","rvol":4.5}
    ]})
    refused=requests.HTTPError("Access denied",
        response=SimpleNamespace(status_code=403))
    session=Session({TICKERS_URL:refused,
      FALLBACK_TICKER_MAP:requests.ConnectionError("mirror also unavailable")})
    out=collect({"stocks":[]},now=NOW,session=session,
                agent="Test test@example.com",pause=lambda _:None)
    assert out["status"]=="UNAVAILABLE"
    assert out["coverage"]["issuers_inspected"]==0
    assert out["coverage"]["filings_verified"]==0
    assert not out["filings"]
    assert out["coverage"]["errors"]["ticker_map"]==403
    assert out["policy"]["positive_news_inferred"] is False


def test_missing_recent_sec_filings_is_not_bullish_market_news():
    session=Session({
        TICKERS_URL:{"0":{"ticker":"RGC","cik_str":111,"title":"Regencell"}},
        f"{SUBMISSIONS_BASE}CIK0000000111.json":report(111,["8-K"],dates=["2026-06-01"])
    })
    out=collect({"stocks":[]},now=NOW,session=session,
                agent="Test test@example.com",pause=lambda _:None,max_symbols=1)
    assert out["status"]=="NO_RECENT_FILINGS"
    assert out["filings"]==[]


def test_stale_mirror_can_nominate_cik_only_when_current_sec_confirms_ticker():
    denied=requests.HTTPError("403",
        response=SimpleNamespace(status_code=403))
    submitted=report(111,["8-K"])
    submitted["tickers"]=["RGC"]
    submitted["name"]="Official Regencell EDGAR registrant"
    session=Session({
        TICKERS_URL:denied,
        FALLBACK_TICKER_MAP:{"RGC":"0000000111"},
        f"{SUBMISSIONS_BASE}CIK0000000111.json":submitted,
    })
    result=collect({"stocks":[]},now=NOW,session=session,
                   agent="Test tester@example.com",pause=lambda _:None,max_symbols=1)
    assert result["coverage"]["filings_verified"]==1
    assert result["ticker_mapping_source"].startswith("UNVERIFIED_2025_MIRROR")
    assert result["ticker_mapping_mirror_snapshot_date"]=="2025-02-28"
    assert result["filings"][0]["issuer"]=="Official Regencell EDGAR registrant"
    assert result["status"]=="PARTIAL"  # Initial SEC ticker map was blocked.
    assert result["coverage"]["errors"]["ticker_map"]==403


def test_stale_mirror_ticker_mismatch_cannot_publish_another_issuer_news():
    denied=requests.HTTPError("403", response=SimpleNamespace(status_code=403))
    submitted=report(111,["8-K"])
    submitted["tickers"]=["UNRELATED"]
    session=Session({
        TICKERS_URL:denied,
        FALLBACK_TICKER_MAP:{"RGC":"0000000111"},
        f"{SUBMISSIONS_BASE}CIK0000000111.json":submitted,
    })
    result=collect({"stocks":[]},now=NOW,session=session,
                   agent="Test tester@example.com",pause=lambda _:None,max_symbols=1)
    assert result["filings"]==[]
    assert result["coverage"]["errors"]["RGC"]=="SEC_ISSUER_TICKER_NOT_CONFIRMED"


def test_official_sec_403_opens_bounded_automatic_retry_without_repeating_calls():
    from datetime import timedelta

    refused=requests.HTTPError("403",response=SimpleNamespace(status_code=403))
    session=Session({
        TICKERS_URL:refused,
        FALLBACK_TICKER_MAP:{"RGC":"0000000111"},
        f"{SUBMISSIONS_BASE}CIK0000000111.json":refused,
    })
    first=collect({"stocks":[]},now=NOW,session=session,
                  agent="Research tester@example.com",pause=lambda _:None,
                  max_symbols=1)
    assert first["status"]=="UNAVAILABLE"
    assert first["refusal_reason"]=="HTTP_403"
    assert first["source_retry_after"]==(NOW+timedelta(hours=6)).isoformat()
    first_call_count=len(session.calls)
    quiet=collect({"stocks":[]},now=NOW+timedelta(hours=1),session=session,
                  agent="Research tester@example.com",pause=lambda _:None,
                  max_symbols=1,previous=first)
    assert quiet["status"]=="UNAVAILABLE"
    assert quiet["coverage"]["errors"]=={"sec_api":"COOLDOWN_ACTIVE"}
    assert quiet["source_retry_after"]==first["source_retry_after"]
    assert quiet["filings"]==[]
    assert len(session.calls)==first_call_count
    recovered=Session({
        TICKERS_URL:{"0":{"ticker":"RGC","cik_str":111,"title":"Regencell"}},
        f"{SUBMISSIONS_BASE}CIK0000000111.json":report(111,["8-K"]),
    })
    later=collect({"stocks":[]},now=NOW+timedelta(hours=7),
                  session=recovered,agent="Research tester@example.com",
                  pause=lambda _:None,max_symbols=1,previous=quiet)
    assert later["coverage"]["issuers_inspected"]==1
    assert later["coverage"]["filings_verified"]==1
    assert later["source_retry_after"] is None
    assert recovered.calls


def test_tampered_sec_cooldown_cannot_disable_official_requests():
    from datetime import timedelta

    previous={
        "schema":"ghazi.sec_issuer_pulse.v1",
        "generated_at":NOW.isoformat(),
        "source_retry_after":(NOW+timedelta(days=30)).isoformat(),
        "refusal_reason":"HTTP_403",
    }
    session=Session({
        TICKERS_URL:{"0":{"ticker":"RGC","cik_str":111,"title":"Regencell"}},
        f"{SUBMISSIONS_BASE}CIK0000000111.json":report(111,["8-K"]),
    })
    result=collect({"stocks":[]},now=NOW,session=session,
                  agent="Research tester@example.com",pause=lambda _:None,
                  max_symbols=1,previous=previous)
    assert session.calls and session.calls[0][0]==TICKERS_URL
    assert result["coverage"]["filings_verified"]==1


def test_sec_8k_item_202_302_distinguishes_earnings_and_equity_sale_review():
    source=report(111,["8-K","8-K","10-K","S-3"],
                  items=["2.02,9.01","1.01, 3.02,9.01","",""])
    rows=parse_submissions("RGC",111,"Regencell",source,now=NOW)
    assert len(rows)==4
    earnings=next(row for row in rows if row["earnings_release_reported"])
    assert earnings["eight_k_items"]==["2.02","9.01"]
    assert "EARNINGS_RELEASE_REVIEW" in earnings["event_topics"]
    assert not earnings["earnings_beat_verified"]
    assert not earnings["potential_dilution_review"]
    risk=next(row for row in rows if "3.02" in row["eight_k_items"])
    assert risk["potential_dilution_review"] is True
    assert "UNREGISTERED_EQUITY_SALE_REVIEW" in risk["event_topics"]
    assert risk["new_shares_issued_verified"] is False
    assert next(row for row in rows if row["form"]=="10-K")["event_topics"]==[
        "PERIODIC_FINANCIAL_REPORT_REVIEW"]
    offering=next(row for row in rows if row["form"]=="S-3")
    assert offering["potential_dilution_review"] is True
    assert not offering["new_shares_issued_verified"]
    assert all(row["positive_price_impact_verified"] is False for row in rows)


def test_missing_or_misaligned_sec_items_do_not_invent_results_or_issuance():
    original=report(111,["8-K","8-K"],items=["2.02","3.02"])
    original["filings"]["recent"]["items"]=["2.02"]
    rows=parse_submissions("RGC",111,"Regencell",original,now=NOW)
    assert len(rows)==2
    assert all(row["eight_k_items"]==[] for row in rows)
    assert all(row["eight_k_items_available"] is False for row in rows)
    bad=report(111,["8-K"],items=["2.02 and 3.02 script://evil"])
    rows=parse_submissions("RGC",111,"Regencell",bad,now=NOW)
    assert rows[0]["eight_k_items"]==["2.02","3.02"]
    assert rows[0]["earnings_beat_verified"] is False
    assert rows[0]["new_shares_issued_verified"] is False


def test_8k_item_malformed_future_date_and_wrong_cik_fail_closed():
    report_data=report(111,["8-K"],dates=["2027-01-01"],items=["2.02"])
    assert parse_submissions("RGC",111,"Regencell",report_data,now=NOW)==[]
    assert parse_submissions("RGC",222,"Unrelated",report_data,now=NOW)==[]
