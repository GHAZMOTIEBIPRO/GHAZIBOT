from options_radar.sec_filing_evidence import parse_recent_filings


def test_sec_filing_evidence_is_research_only():
    data = {"cik": 320193, "filings": {"recent": {
        "accessionNumber": ["0000320193-26-000001"],
        "form": ["8-K"],
        "filingDate": ["2026-10-07"],
        "primaryDocument": ["filing.htm"],
    }}}
    result = parse_recent_filings(data)
    assert len(result) == 1
    assert result[0]["official_catalyst_url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/filing.htm"
    )
    assert result[0]["bullish_catalyst_verified"] is False
    assert result[0]["research_only"] is True


def test_sec_filing_evidence_rejects_bad_path_and_accession():
    for accession, document in [
        ("../bad", "filing.htm"),
        ("0000320193-26-000001", "../secrets"),
        ("0000320193-26-000001", "https://evil.example"),
    ]:
        data = {"cik": 320193, "filings": {"recent": {
            "accessionNumber": [accession], "form": ["8-K"],
            "filingDate": ["2026-10-07"], "primaryDocument": [document],
        }}}
        assert parse_recent_filings(data) == []


def test_sec_filing_evidence_rejects_misaligned_and_bad_date():
    assert parse_recent_filings({"cik": 1, "filings": {"recent": {
        "accessionNumber": ["0000000001-26-000001"], "form": ["8-K"],
        "filingDate": [], "primaryDocument": ["x.htm"],
    }}}) == []
    assert parse_recent_filings({"cik": 1, "filings": {"recent": {
        "accessionNumber": ["0000000001-26-000001"], "form": ["8-K"],
        "filingDate": ["2026-99-99"], "primaryDocument": ["x.htm"],
    }}}) == []
