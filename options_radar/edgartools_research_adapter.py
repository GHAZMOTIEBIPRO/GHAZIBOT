"""Optional EdgarTools adapter for research-only SEC catalyst discovery.

Requires separately installed edgartools and SEC-compliant user identity.
Never treats a filing as proof of a bullish price move.
"""
from __future__ import annotations

import os
from typing import Any


SUPPORTED_FORMS = ("4", "8-K", "S-3", "424B5")


def recent_company_filings(symbol: str, *, limit: int = 5) -> dict[str, Any]:
    ticker = str(symbol or "").strip().upper()
    if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
        return {"symbol": ticker, "status": "UNAVAILABLE", "reason": "invalid_symbol", "filings": []}
    try:
        from edgar import Company  # type: ignore[import-not-found]
    except ImportError:
        return {"symbol": ticker, "status": "UNAVAILABLE", "reason": "edgartools_not_installed", "filings": []}
    try:
        from edgar import set_identity  # type: ignore[import-not-found]
        identity = os.getenv("SEC_EDGAR_IDENTITY", "").strip()
        if not identity:
            return {"symbol": ticker, "status": "UNAVAILABLE", "reason": "sec_identity_not_configured", "filings": []}
        set_identity(identity)
        company = Company(ticker)
        filings = company.get_filings(form=list(SUPPORTED_FORMS)).head(max(1, min(int(limit), 20)))
        output = []
        for filing in filings:
            form = str(getattr(filing, "form", ""))
            if form not in SUPPORTED_FORMS:
                continue
            output.append({
                "form": form,
                "filing_date": str(getattr(filing, "filing_date", "")),
                "accession_number": str(getattr(filing, "accession_no", "")),
                "source": "SEC_EDGAR_VIA_EDGARTOOLS",
                "classification": "RESEARCH_ONLY",
                "insider_purchase_verified": False,
                "price_direction": "UNKNOWN",
            })
        return {"symbol": ticker, "status": "RESEARCH", "filings": output}
    except Exception as exc:
        return {"symbol": ticker, "status": "UNAVAILABLE", "reason": type(exc).__name__, "filings": []}
