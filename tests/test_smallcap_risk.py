"""SEC risk context: registration is not issuance, shares outstanding are not float, unknown stays unknown."""
from datetime import date

from options_radar import smallcap_risk as r

AS_OF = date(2026, 11, 30)


def _subs(rows):
    keys = ("form", "filingDate", "items", "accessionNumber")
    return {"filings": {"recent": {k: [row[i] for row in rows] for i, k in enumerate(keys)}}}


def test_registration_alone_is_capacity_not_issuance():
    a = r.assess(_subs([("S-3", "2026-10-01", "", "0001-26-000001"), ("10-Q", "2026-11-10", "", "x")]), None, as_of=AS_OF)
    assert a["dilution"] == "CAPACITY_ONLY" and set(a["filings"]) == {"SHELF_REGISTERED"}
    assert "ليس إصداراً" in r.line_ar(a) and "الأسهم القائمة غير متاحة" in r.line_ar(a)


def test_takedown_and_unregistered_sale_are_actual_issuance_and_old_filings_ignored():
    a = r.assess(_subs([("424B5", "2026-11-20", "", "a"), ("8-K", "2026-11-21", "3.02,9.01", "b"),
                        ("8-K", "2026-11-25", "5.03", "c"), ("S-1", "2025-01-01", "", "old")]), None, as_of=AS_OF)
    assert a["dilution"] == "ACTUAL_ISSUANCE_LIKELY"
    assert set(a["filings"]) == {"OFFERING_SUPPLEMENT", "UNREGISTERED_SALE", "CHARTER_AMENDMENT"}
    assert "قد يكون تقسيماً عكسياً" in r.line_ar(a)  # a charter amendment is reviewed, not assumed a split


def test_shares_outstanding_with_date_never_called_float():
    facts = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        {"val": 10_000_000, "end": "2026-05-01", "filed": "2026-05-10", "form": "10-Q"},
        {"val": 12_500_000, "end": "2026-11-01", "filed": "2026-11-08", "form": "10-Q"}]}}}}}
    a = r.assess(_subs([]), facts, as_of=AS_OF)
    assert a["shares_outstanding"]["shares"] == 12_500_000 and a["float_shares"] == "UNKNOWN"
    assert a["dilution"] == "NONE_FILED_180D" and "لا يعني انعدام المخاطر" in r.line_ar(a)
    assert "ليست الأسهم الحرة" in r.line_ar(a) and a["halt_status"] == "UNKNOWN"


def test_without_sec_access_everything_is_unknown_and_nothing_is_fetched():
    calls = []
    assert r.fetch("1622229", "", opener=lambda *a, **k: calls.append(a)) == (None, None) and not calls
    a = r.assess(None, None, as_of=AS_OF)
    assert a["dilution"] == "UNKNOWN" and not a["opportunity_confirmed"] and "غير مفحوص" in r.line_ar(a)
