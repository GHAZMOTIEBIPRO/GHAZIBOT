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
    # ABCD: two HIGH events (approval 5 days old, offering 3 days old) outrank RVSP's one.
    assert symbols[:2] == ["ABCD", "RVSP"] and "OLDX" not in symbols and "FAKE" not in symbols
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
    assert report["sources"] == {"openfda": False, "sec_edgar": False, "sec_status": "MISSING", "clinicaltrials": False, "clinicaltrials_status": "MISSING"}


def test_workflow_is_single_writer_without_a_price_input():
    text = (ROOT / ".github/workflows/catalyst-watchlist.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    assert wf[True]["schedule"] == [{"cron": "15 5 * * 1-5"}, {"cron": "15 8 * * 1-5"}] and "--prices" not in text
    # readers (e.g. the private scan) may mention the file; only one workflow writes or commits it
    writers = [p.name for p in (ROOT / ".github/workflows").glob("*.yml")
               if any("catalyst_watchlist.json" in line and ("--output" in line or "git add" in line)
                      for line in p.read_text(encoding="utf-8").splitlines())]
    assert writers == ["catalyst-watchlist.yml"]


def test_most_important_catalyst_is_listed_first_and_latest_date_kept():
    fda = {"approvals": [
        {"event_type": "APPROVAL_SUPPLEMENT", "date": "2026-10-19", "ticker": "MRKX", "importance": "LOW"},
        {"event_type": "APPROVAL_ORIGINAL", "date": "2026-10-10", "ticker": "MRKX", "importance": "HIGH"}],
        "recalls": []}
    entry = cw.build(fda, None, None, NOW)["watchlist"][0]
    assert [c["kind"] for c in entry["catalysts"]] == ["FDA_APPROVAL", "FDA_SUPPLEMENT"]
    assert entry["latest_date"] == "2026-10-19" and entry["highest_importance"] == "HIGH"


def test_score_uses_strength_recency_reliability_and_flags_risk():
    fda = {"approvals": [
        {"event_type": "APPROVAL_ORIGINAL", "date": "2026-10-20", "ticker": "NEWM", "importance": "HIGH",
         "submission_class": "Type 1 - New Molecular Entity", "match_method": "exact_normalised_name"},
        {"event_type": "APPROVAL_ORIGINAL", "date": "2026-10-20", "ticker": "ALIAS", "importance": "HIGH",
         "submission_class": "Type 5 - New Formulation", "match_method": "reviewed_sponsor_alias"},
        {"event_type": "APPROVAL_ORIGINAL", "date": "2026-09-25", "ticker": "OLDH", "importance": "HIGH",
         "match_method": "exact_normalised_name"},
        {"event_type": "APPROVAL_ORIGINAL", "date": "2026-10-20", "ticker": "LLY", "importance": "HIGH",
         "match_method": "exact_normalised_name"}],
        "recalls": [{"event_type": "RECALL", "date": "2026-10-20", "ticker": "RCLL", "importance": "HIGH"}]}
    report = cw.build(fda, None, None, NOW)
    by = {e["symbol"]: e for e in report["watchlist"]}
    # new molecule > same-day formulation via alias > same event 26 days old
    assert by["NEWM"]["catalyst_score"] > by["ALIAS"]["catalyst_score"] > by["OLDH"]["catalyst_score"]
    assert by["NEWM"]["catalyst_score"] == round((35 + 10) * (0.4 + 0.6 * 29 / 30), 1)
    assert by["RCLL"]["risk_flags"] == ["سحب منتج Class I"] and by["RCLL"]["risk_level"] == "HIGH"
    assert all(e["candidate_status"] == "PRICE_VERIFICATION_NEEDED" for e in report["watchlist"])
    # No documented size: nothing is called small; the reference list is labelled as a list.
    assert by["LLY"]["universe"] == "KNOWN_LARGE_ISSUER_LIST"
    assert by["NEWM"]["universe"] == "MARKET_CAP_UNVERIFIED" and by["NEWM"]["market_cap"]["status"] == "UNVERIFIED"
    assert report["market_cap_unverified_candidates"][0] == "NEWM" and report["public_float_ranked"] == []
    assert report["size_rules"]["sources_status"] == "SEC_SIZE_DATA_UNAVAILABLE"
    assert "غير متحقق" in report["size_rules"]["note_ar"]
    # Production 2026-10-25 listed these large/mid caps as small-cap candidates.
    assert {"TAK", "BNTX", "MRNA", "TEVA", "BAX", "JAZZ", "INCY"} <= cw.KNOWN_LARGE_ISSUERS
    assert "ليست توقعًا" in report["ranking_rules"]["note_ar"] and report["ranking_rules"]["top_n"] == 3


def test_size_fields_stay_separate_and_nothing_is_called_small_from_sec_thresholds():
    fda = {"approvals": [
        {"event_type": "APPROVAL_ORIGINAL", "date": "2026-10-20", "ticker": t, "importance": "HIGH"}
        for t in ("TINY", "BIGC", "TEVA", "OLDF", "BADU")], "recalls": []}
    url = "https://www.sec.gov/Archives/edgar/data/1/2/"
    srch = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1"
    sizes = {"symbols": {
        "TINY": {"public_float_value": {"usd": 90e6, "as_of": "2026-06-30", "source_url": url},
                 "shares_outstanding": {"shares": 12_000_000, "as_of": "2026-08-01", "source_url": url},
                 "sec_filer_status": {"category": "Non-accelerated filer", "smaller_reporting_company": True,
                                      "exchanges": ["Nasdaq"], "source_url": srch}},
        "BIGC": {"public_float_value": {"usd": 5e9, "as_of": "2026-06-30", "source_url": url}},
        "TEVA": {"sec_filer_status": {"category": "Accelerated filer", "source_url": srch}},
        "OLDF": {"public_float_value": {"usd": 90e6, "as_of": "2024-06-28", "source_url": url}},
        "BADU": {"public_float_value": {"usd": 90e6, "as_of": "2026-06-30", "source_url": "https://evil.example/x"}}}}
    report = cw.build(fda, None, None, NOW, None, sizes)
    by = {e["symbol"]: e for e in report["watchlist"]}
    tiny = by["TINY"]
    # SEC data is evidence only: market cap stays unverified and float shares unavailable
    assert tiny["universe"] == "MARKET_CAP_UNVERIFIED" and tiny["market_cap"]["status"] == "UNVERIFIED"
    assert tiny["float_shares"]["status"] == "UNAVAILABLE"
    assert tiny["public_float_value"] == {"usd": 90e6, "as_of": "2026-06-30", "source_url": url, "stale": False}
    assert tiny["shares_outstanding"]["shares"] == 12_000_000
    assert tiny["sec_filer_status"]["category"] == "Non-accelerated filer"
    assert tiny["sec_filer_status"]["smaller_reporting_company"] is True
    assert by["OLDF"]["public_float_value"]["stale"] is True and by["BADU"]["public_float_value"] is None
    assert [r["symbol"] for r in report["public_float_ranked"]] == ["TINY", "BIGC"]
    assert "small_cap_candidates" not in report and "SIZE_VERIFIED_SMALL" not in str(report)
    # the manual large list is reviewed against SEC filer status
    assert report["list_review"] == [{"symbol": "TEVA", "sec_filer_status": "Accelerated filer"}]
    # Low price is a separate test: no price input, so nothing is under $10.
    assert all(e["sub10_confirmed"] is False for e in report["watchlist"])


def test_impact_classes_and_one_record_per_underlying_event():
    url = "https://clinicaltrials.gov/study/NCT01234567"
    base = {"source": "ClinicalTrials.gov", "official_registry_only": True, "outcome_direction": "NOT_INFERRED",
            "match_method": "exact_normalised_name", "symbol": "GSK", "source_url": url, "importance": "LOW"}
    items = [{**base, "kind": "TRIAL_REGISTRY_UPDATE", "date": "2026-10-18"},
             {**base, "kind": "TRIAL_REGISTRY_UPDATE", "date": "2026-10-20"},
             {**base, "kind": "TRIAL_RESULTS_POSTED", "date": "2026-10-19", "importance": "MEDIUM"}]
    unique = cw.dedupe(items)
    assert sorted((i["kind"], i["date"]) for i in unique) == [("TRIAL_REGISTRY_UPDATE", "2026-10-20"),
                                                              ("TRIAL_RESULTS_POSTED", "2026-10-19")]
    assert cw.IMPACT["TRIAL_REGISTRY_UPDATE"] == "ADMINISTRATIVE"
    assert cw.IMPACT["TRIAL_RESULTS_POSTED"] == "RESULTS_POSTED_DIRECTION_UNKNOWN"


def test_daily_plan_does_not_list_an_administrative_update_as_a_catalyst():
    from scripts import build_daily_plan as bdp
    watch = {"watchlist": [
        {"symbol": "ADMN", "catalysts": [{"kind": "TRIAL_REGISTRY_UPDATE", "date": "2026-10-20"}]},
        {"symbol": "RSLT", "catalysts": [{"kind": "TRIAL_REGISTRY_UPDATE", "date": "2026-10-20"},
                                         {"kind": "TRIAL_RESULTS_POSTED", "date": "2026-10-19"}]}]}
    listed = bdp.catalysts_today(watch, NOW)
    assert [(c["symbol"], c["kind"]) for c in listed] == [("RSLT", "TRIAL_RESULTS_POSTED")]


def test_events_keep_event_date_source_update_and_first_detection_apart():
    fda = {**FDA, "source_last_updated": {"approvals": "2026-10-20", "recalls": "2026-10-14"}}
    first = cw.build(fda, None, None, NOW)
    events = {e["symbol"]: e for e in first["events"]}
    assert events["ABCD"]["date"] == "2026-10-16"              # FDA action date
    assert events["ABCD"]["source_updated"] == "2026-10-20"    # openFDA dataset update, not a publication time
    assert events["AMRX"]["source_updated"] == "2026-10-14"
    assert events["ABCD"]["first_seen_at"] == NOW.isoformat() and events["ABCD"]["first_seen_basis"] == "THIS_RUN"
    assert "first_seen_at" in first["event_time_fields"]
    # A later run carries the first detection instead of resetting it.
    later = cw.build(fda, None, None, NOW + timedelta(hours=6), previous=first)
    again = {e["symbol"]: e for e in later["events"]}
    assert again["ABCD"]["first_seen_at"] == NOW.isoformat() and again["ABCD"]["first_seen_basis"] == "CARRIED"


def test_events_listed_before_tracking_get_no_invented_detection_time():
    old = cw.build(FDA, None, None, NOW)
    for entry in old["watchlist"]:            # a file written before the field existed
        for c in entry["catalysts"]:
            c.pop("first_seen_at", None)
            c.pop("first_seen_basis", None)
    old.pop("events")
    report = cw.build(FDA, None, None, NOW + timedelta(hours=1), previous=old)
    abcd = next(e for e in report["events"] if e["symbol"] == "ABCD")
    assert abcd["first_seen_at"] is None and abcd["first_seen_basis"] == "BEFORE_TRACKING"


def test_events_list_is_complete_beyond_the_per_ticker_cap():
    rows = [{"event_type": "APPROVAL_SUPPLEMENT", "date": f"2026-10-{d:02d}", "ticker": "MANY", "importance": "LOW",
             "products": [f"P{d}"], "official_url": f"https://www.accessdata.fda.gov/{d}"} for d in range(5, 20)]
    report = cw.build({"approvals": rows, "recalls": []}, None, None, NOW)
    assert len(report["watchlist"][0]["catalysts"]) == cw.MAX_CATALYSTS
    assert len([e for e in report["events"] if e["symbol"] == "MANY"]) == 15
    assert [e["date"] for e in report["events"]] == sorted((e["date"] for e in report["events"]), reverse=True)

