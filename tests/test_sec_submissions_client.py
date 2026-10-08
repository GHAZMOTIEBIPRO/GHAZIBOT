from io import BytesIO
from unittest.mock import patch

import pytest

from options_radar.sec_submissions_client import fetch_sec_filings


class FakeResponse:
    def __init__(self, url, data):
        self.url, self.data = url, data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def geturl(self):
        return self.url

    def read(self, size):
        return self.data.read(size)


def test_sec_client_reads_official_cik_only():
    body = (b'{"cik":320193,"filings":{"recent":{"accessionNumber":'
            b'["0000320193-26-000001"],"form":["8-K"],'
            b'"filingDate":["2026-10-07"],"primaryDocument":["filing.htm"]}}}')
    def fake_open(request, timeout):
        assert request.full_url == "https://data.sec.gov/submissions/CIK0000320193.json"
        assert timeout == 10
        return FakeResponse(request.full_url, BytesIO(body))
    with patch("options_radar.sec_submissions_client.urlopen", fake_open):
        result = fetch_sec_filings("320193", user_agent="BlackBox Research admin@example.com")
    assert len(result) == 1
    assert result[0]["research_only"] is True


def test_sec_client_rejects_untrusted_parameters_before_network():
    with pytest.raises(ValueError):
        fetch_sec_filings("../bad", user_agent="BlackBox Research admin@example.com")
    with pytest.raises(ValueError):
        fetch_sec_filings("320193", user_agent="anonymous")


def test_sec_client_rejects_cik_mismatch():
    def fake_open(request, timeout):
        return FakeResponse(request.full_url, BytesIO(b'{"cik":42,"filings":{"recent":{}}}'))
    with patch("options_radar.sec_submissions_client.urlopen", fake_open):
        with pytest.raises(ValueError, match="mismatch"):
            fetch_sec_filings("320193", user_agent="BlackBox Research admin@example.com")
