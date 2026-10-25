"""SEC public float producer for size classification (fixture responses, no network)."""
from datetime import datetime, timezone

from scripts import build_issuer_sizes as sizes

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.content = payload, status, b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            err = RuntimeError(f"HTTP {self.status_code}")
            err.response = self
            raise err

    def json(self):
        return self.payload


class Session:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        reply = self.replies.get(url, Response({}, 404))
        return reply if isinstance(reply, Response) else Response(reply)


TICKERS = {"0": {"ticker": "TINY", "cik_str": 111, "title": "Tiny Bio"},
           "1": {"ticker": "NOFL", "cik_str": 222, "title": "No Float Inc"}}
CONCEPT = {"units": {"USD": [
    {"val": 80e6, "end": "2025-06-30", "form": "10-K", "accn": "0000000111-25-000001", "filed": "2025-09-01"},
    {"val": 95e6, "end": "2026-06-30", "form": "10-K", "accn": "0000000111-26-000002", "filed": "2026-09-01"},
    {"val": 999e9, "end": "2026-09-30", "form": "10-Q", "accn": "0000000111-26-000003"}]}}


def test_latest_annual_public_float_with_filing_link_and_identity_header():
    session = Session({sizes.TICKERS_URL: TICKERS,
                       sizes.CONCEPT_URL.format(cik=111): CONCEPT,
                       sizes.CONCEPT_URL.format(cik=222): {"units": {"USD": []}}})
    report = sizes.build(["TINY", "NOFL", "ZZZZ"], agent="Owner Name owner@example.com", session=session,
                         now=NOW, pause=0)
    tiny = report["symbols"]["TINY"]
    assert tiny["public_float_usd"] == 95e6 and tiny["public_float_as_of"] == "2026-06-30" and tiny["form"] == "10-K"
    assert tiny["source_url"] == "https://www.sec.gov/Archives/edgar/data/111/000000011126000002/"
    assert report["errors"] == {"NOFL": "NO_ANNUAL_PUBLIC_FLOAT", "ZZZZ": "NO_SEC_CIK"}
    assert all(h["User-Agent"] == "Owner Name owner@example.com" for _, h in session.calls)
    assert report["status"] == "OK"


def test_missing_identity_and_refusal_are_reported_without_retry_loops():
    assert sizes.build(["TINY"], agent=None, now=NOW)["status"] == "SEC_IDENTITY_MISSING"
    session = Session({sizes.TICKERS_URL: Response({}, 403)})
    refused = sizes.build(["TINY"], agent="a b@c.d", session=session, now=NOW, pause=0)
    assert refused["status"] == "SEC_REFUSED_HTTP_403" and len(session.calls) == 1
    session = Session({sizes.TICKERS_URL: TICKERS, sizes.CONCEPT_URL.format(cik=111): Response({}, 429)})
    throttled = sizes.build(["TINY", "NOFL"], agent="a b@c.d", session=session, now=NOW, pause=0)
    assert throttled["errors"]["TINY"] == "HTTP_429" and "NOFL" not in throttled["errors"]
