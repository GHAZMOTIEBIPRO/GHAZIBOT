from io import BytesIO
from unittest.mock import patch

from scripts.sec_research_probe import probe


class Response:
    def __init__(self, url, payload):
        self.url, self.payload = url, BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def geturl(self):
        return self.url

    def read(self, size):
        return self.payload.read(size)


def test_probe_maps_ticker_to_official_filings():
    mapping = b'{"0":{"ticker":"AAPL","cik_str":320193,"title":"Apple Inc."}}'
    submissions = (b'{"cik":320193,"filings":{"recent":{"accessionNumber":'
                   b'["0000320193-26-000001"],"form":["8-K"],'
                   b'"filingDate":["2026-10-07"],"primaryDocument":["filing.htm"]}}}')
    def fake_open(request, timeout):
        return Response(request.full_url, mapping if "company_tickers" in request.full_url else submissions)
    with patch("scripts.sec_research_probe.urlopen", fake_open), patch(
        "options_radar.sec_submissions_client.urlopen", fake_open
    ):
        result = probe("AAPL", user_agent="BlackBox Research admin@example.com")
    assert result["status"] == "SEC_RESEARCH_OK"
    assert result["identity"]["cik"] == 320193
    assert result["filing_count"] == 1
    assert result["research_only"] is True
    assert result["telegram_enabled"] is False
