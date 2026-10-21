"""Catalyst watchlist: official events only, no under-$10 claim without a permitted current quote."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("catalyst_watchlist_under_test",
                                               ROOT / "scripts" / "build_catalyst_watchlist.py")
cw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cw)
NOW = datetime(2026, 10, 21, 14, 0, tzinfo=timezone.utc)

FDA = {"approvals": [
    {"event_type": "APPROVAL_ORIGINAL", "date": "2026-10-16", "ticker": "ABCD", "importance": "HIGH",
     "products": ["NEWDRUG"], "importance_reason": "Type 1", "official_url": "https://www.accessdata.fda.gov/x",
     "match_method": "exact_normalised_name"},
    {"event_type": "APPROVAL_SUPPLEMENT", "date": "2026-10-15", "ticker": "ACAD", "importance": "LOW",
     "products": ["DAYBUE"], "match_method": "reviewed_sponsor_alias"},
    {"event_type": "APPROVAL_ORIGINAL", "date": "2026-10-16", "ticker": None, "importance": "HIGH"},
    {"event_type": "APPROVAL_ORIGINAL", "date": "2026-08-01", "ticker": "OLDX", "importance": "HIGH"}],
    "recalls": [{"event_type": "RECALL", "date": "2026-10-07", "ticker": "AMRX", "importance": "MEDIUM",
                 "product": "Estradiol Gel"}]}


def _sec(status="OK"):
    return {"status": status, "filings": [
        {"symbol": "ABCD", "form": "424B5", "filing_date": "2026-10-18", "original_filing_confirmed": True,
         "source_url": "https://www.sec.gov/Archives/edgar/data/1/2/a.htm",
         "event_topics": ["OFFERING_OR_REGISTRATION_TERMS_REVIEW"]},
        {"symbol": "RVSP", "form": "8-K", "filing_date": "2026-10-19", "original_filing_confirmed": True,
         "source_url": "https://www.sec.gov/Archives/edgar/data/3/4/b.htm",
         "event_topics": ["SHAREHOLDER_RIGHTS_OR_CHARTER_CHANGE_REVIEW"]},
        {"symbol": "FAKE", "form": "8-K", "filing_date": "2026-10-19", "original_filing_confirmed": True,
         "source_url": "https://evil.example/x", "event_topics": ["MATERIAL_AGREEMENT_REVIEW"]}]}


def test_watchlist_from_official_events_ranked_without_price_claims():
    report = cw.build(FDA, _sec(), None, NOW)
    symbols = [e["symbol"] for e in report["watchlist"]]
    assert symbols[:2] == ["RVSP", "ABCD"] and "OLDX" not in symbols and "FAKE" not in symbols
    abcd = next(e for e in report["watchlist"] if e["symbol"] == "ABCD")
    assert abcd["dilution_risk"] is True and abcd["catalyst_count"] == 2
    assert {c["source"] for c in abcd["catalysts"]} == {"openFDA", "SEC EDGAR"}
    assert next(e for e in report["watchlist"] if e["symbol"] == "RVSP")["charter_or_reverse_split_review"]
    assert all(e["price_band"] == "UNVERIFIED" and e["sub10_confirmed"] is False
               and e["price_confirmed_signal"] is False for e in report["watchlist"])
    assert report["price_confirmed_signals"] == []
    assert report["price_confirmation"]["status"] == "NO_PERMITTED_PRICE_SOURCE"
    assert report["research_only"] is True and report["decision_authority"] is False


def test_blocked_or_archive_sec_is_not_used():
    for status in ("UNAVAILABLE", "BULK_ARCHIVE_UNDATED"):
        report = cw.build(FDA, _sec(status), None, NOW)
        assert report["sources"]["sec_edgar"] is False
        assert {c["source"] for e in report["watchlist"] for c in e["catalysts"]} == {"openFDA"}


def test_under_10_only_from_a_current_quote_with_display_rights():
    fresh = (NOW - timedelta(minutes=5)).isoformat()
    cases = {
        "permitted": ({"price": 4.2, "quote_time": fresh, "public_display_permitted": True}, "UNDER_10", True),
        "no_rights": ({"price": 4.2, "quote_time": fresh}, "UNVERIFIED", False),
        "stale": ({"price": 4.2, "quote_time": (NOW - timedelta(hours=3)).isoformat(),
                   "public_display_permitted": True}, "UNVERIFIED", False),
        "no_time": ({"price": 4.2, "public_display_permitted": True}, "UNVERIFIED", False),
        "future": ({"price": 4.2, "quote_time": (NOW + timedelta(minutes=5)).isoformat(),
                    "public_display_permitted": True}, "UNVERIFIED", False),
        "above": ({"price": 12.0, "quote_time": fresh, "public_display_permitted": True}, "10_OR_MORE", False),
    }
    for name, (quote, band, sub10) in cases.items():
        result = cw.price_band("ABCD", {"quotes": {"ABCD": quote}}, NOW)
        assert (result["price_band"], result["sub10_confirmed"]) == (band, sub10), name


def test_no_inputs_is_an_explicit_empty_report():
    report = cw.build(None, None, None, NOW)
    assert report["status"] == "NO_RECENT_CATALYSTS" and report["watchlist"] == []
    assert report["sources"] == {"openfda": False, "sec_edgar": False, "sec_status": "MISSING"}


def test_workflow_is_single_writer_without_a_price_input():
    text = (ROOT / ".github/workflows/catalyst-watchlist.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    assert "schedule" not in wf[True] and "--prices" not in text
    writers = [p.name for p in (ROOT / ".github/workflows").glob("*.yml")
               if "catalyst_watchlist.json" in p.read_text(encoding="utf-8")]
    assert writers == ["catalyst-watchlist.yml"]
