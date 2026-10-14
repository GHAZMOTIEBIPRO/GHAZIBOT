import sys
from types import SimpleNamespace
from options_radar.edgartools_research_adapter import recent_company_filings


def test_missing_dependency_is_fail_closed(monkeypatch):
    monkeypatch.setitem(sys.modules, "edgar", None)
    result = recent_company_filings("MU")
    assert result["status"] == "UNAVAILABLE"
    assert result["filings"] == []


def test_invalid_ticker():
    assert recent_company_filings("../bad")["status"] == "UNAVAILABLE"


def test_filings_do_not_claim_buy_or_direction(monkeypatch):
    class FakeCompany:
        def __init__(self, ticker):
            assert ticker == "MU"
        def get_filings(self, form):
            assert "4" in form
            return SimpleNamespace(head=lambda n: [SimpleNamespace(form="4", filing_date="2026-10-14", accession_no="123")])
    monkeypatch.setenv("SEC_EDGAR_IDENTITY", "Researcher research@example.org")
    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=FakeCompany, set_identity=lambda value: None))
    result = recent_company_filings("MU")
    assert result["status"] == "RESEARCH"
    assert result["filings"][0]["insider_purchase_verified"] is False
    assert result["filings"][0]["price_direction"] == "UNKNOWN"


def test_missing_sec_identity_fails_closed(monkeypatch):
    monkeypatch.delenv("SEC_EDGAR_IDENTITY", raising=False)
    monkeypatch.setitem(sys.modules, "edgar", SimpleNamespace(Company=object, set_identity=lambda value: None))
    assert recent_company_filings("MU")["reason"] == "sec_identity_not_configured"
