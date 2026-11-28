"""SEC risk context: registration -> capacity -> offering -> reported sale; other risks apart; unknown stays unknown."""
from datetime import date

from options_radar import smallcap_risk as r

AS_OF = date(2026, 11, 30)


def _subs(rows):
    keys = ("form", "filingDate", "items", "accessionNumber")
    return {"filings": {"recent": {k: [row[i] for row in rows] for i, k in enumerate(keys)}}}


def test_registration_alone_is_capacity_not_issuance():
    a = r.assess(_subs([("S-3", "2026-10-01", "", "a"), ("10-Q", "2026-11-10", "", "x")]), None, as_of=AS_OF)
    assert a["dilution"] == "CAPACITY_ONLY" and set(a["filings"]) == {"SHELF_REGISTERED"}
    assert "ليس إصداراً" in r.line_ar(a) and "الأسهم القائمة غير متاحة" in r.line_ar(a)


def test_resale_prospectuses_are_not_new_issuance():
    a = r.assess(_subs([("424B3", "2026-11-20", "", "a"), ("424B7", "2026-11-21", "", "b")]), None, as_of=AS_OF)
    assert a["dilution"] == "CAPACITY_ONLY" and set(a["filings"]) == {"RESALE_OR_OTHER_PROSPECTUS"}
    assert "لا تعني إصداراً جديداً" in r.line_ar(a)


def test_offering_prospectus_is_announced_and_only_3_02_reports_a_sale():
    offer = r.assess(_subs([("424B5", "2026-11-20", "", "a")]), None, as_of=AS_OF)
    assert offer["dilution"] == "OFFERING_ANNOUNCED" and "يُقرأ النص" in r.line_ar(offer)
    sold = r.assess(_subs([("424B5", "2026-11-20", "", "a"), ("8-K", "2026-11-21", "3.02,9.01", "b")]), None, as_of=AS_OF)
    assert sold["dilution"] == "ISSUANCE_REPORTED"


def test_other_risks_are_listed_apart_from_dilution_and_old_or_future_filings_ignored():
    a = r.assess(_subs([("8-K", "2026-11-25", "3.01,5.03", "c"), ("S-1", "2025-01-01", "", "old"),
                        ("424B5", "2026-12-05", "", "future")]), None, as_of=AS_OF)
    assert a["dilution"] == "NO_RELEVANT_FILING_FOUND_180D" and a["filings"] == {}
    assert set(a["other_risks"]) == {"LISTING_DEFICIENCY", "CHARTER_AMENDMENT"}
    assert "لا يعني الأمان" in r.line_ar(a) and "قد يكون تقسيماً عكسياً" in r.line_ar(a)


def test_shares_outstanding_dated_as_of_and_ambiguous_classes_unknown():
    facts = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"val": 10_000_000, "end": "2026-05-01", "filed": "2026-05-10", "form": "10-Q"},
        {"val": 12_500_000, "end": "2026-11-01", "filed": "2026-11-08", "form": "10-Q"},
        {"val": 99_000_000, "end": "2026-12-01", "filed": "2026-12-08", "form": "10-K"}]}}}}}
    a = r.assess(_subs([]), facts, as_of=AS_OF)
    assert a["shares_outstanding"]["shares"] == 12_500_000  # the December filing was not available yet
    assert a["float_shares"] == "UNKNOWN" and a["halt_status"] == "UNKNOWN" and "ليست الأسهم الحرة" in r.line_ar(a)
    two_classes = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"val": 5_000_000, "end": "2026-11-01", "filed": "2026-11-08"},
        {"val": 1_000_000, "end": "2026-11-01", "filed": "2026-11-08"}]}}}}}
    assert r.shares_outstanding(two_classes, as_of=AS_OF) is None  # never summed or guessed


def test_without_sec_access_everything_is_unknown_and_nothing_is_fetched():
    calls = []
    assert r.fetch("1622229", "", opener=lambda *a, **k: calls.append(a)) == (None, None) and not calls
    a = r.assess(None, None, as_of=AS_OF)
    assert a["dilution"] == "UNKNOWN" and not a["opportunity_confirmed"] and "غير مفحوص" in r.line_ar(a)
