"""SEC failures are told apart by host and kind, from the response itself."""
from types import SimpleNamespace

import requests

from scripts.build_sec_filing_pulse import sec_refusal


def _err(url, code, text):
    exc = requests.HTTPError("x")
    exc.response = SimpleNamespace(url=url, status_code=code, text=text)
    return exc


def test_identity_rate_other_and_network_are_distinct():
    assert sec_refusal(_err("https://data.sec.gov/submissions/CIK1.json", 403,
                            "<title>SEC.gov | Your Request Originates from an Undeclared Automated Tool</title>")) \
        == "data.sec.gov:IDENTITY_REFUSED"
    assert sec_refusal(_err("https://www.sec.gov/files/company_tickers.json", 403,
                            "<title>SEC.gov | Request Rate Threshold Exceeded</title>")) == "www.sec.gov:RATE_LIMITED"
    assert sec_refusal(_err("https://data.sec.gov/x", 429, "")) == "data.sec.gov:RATE_LIMITED"
    assert sec_refusal(_err("https://www.sec.gov/x", 404, "")) == "www.sec.gov:HTTP_404"
    timeout = requests.ConnectTimeout("t")
    timeout.request = SimpleNamespace(url="https://data.sec.gov/y")
    assert sec_refusal(timeout) == "data.sec.gov:NETWORK_ConnectTimeout"
