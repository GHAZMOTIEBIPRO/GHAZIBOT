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


SHARES = {"units": {"shares": [
    {"val": 11_000_000, "end": "2026-05-01", "form": "10-Q", "accn": "0000000111-26-000001", "filed": "2026-05-10"},
    {"val": 12_500_000, "end": "2026-08-01", "form": "10-Q", "accn": "0000000111-26-000004", "filed": "2026-08-10"}]}}
SUBMISSIONS = {"category": "Non-accelerated filer<br>Smaller reporting company", "exchanges": ["Nasdaq"]}


def test_size_evidence_fields_are_separate_with_links_and_identity_header():
    session = Session({sizes.TICKERS_URL: TICKERS,
                       sizes.CONCEPT_URL.format(cik=111): CONCEPT,
                       sizes.SHARES_URL.format(cik=111): SHARES,
                       sizes.SUBMISSIONS_URL.format(cik=111): SUBMISSIONS,
                       sizes.CONCEPT_URL.format(cik=222): {"units": {"USD": []}},
                       sizes.SUBMISSIONS_URL.format(cik=222): {"category": "Large accelerated filer"}})
    report = sizes.build(["TINY", "NOFL", "ZZZZ"], agent="Owner Name owner@example.com", session=session,
                         now=NOW, pause=0)
    tiny = report["symbols"]["TINY"]
    pf = tiny["public_float_value"]
    assert pf["usd"] == 95e6 and pf["as_of"] == "2026-06-30" and pf["form"] == "10-K"
    assert pf["source_url"] == "https://www.sec.gov/Archives/edgar/data/111/000000011126000002/"
    assert tiny["shares_outstanding"]["shares"] == 12_500_000 and tiny["shares_outstanding"]["as_of"] == "2026-08-01"
    status = tiny["sec_filer_status"]
    assert status["category"] == "Non-accelerated filer" and status["smaller_reporting_company"] is True
    assert status["exchanges"] == ["Nasdaq"]
    assert tiny["market_cap"]["status"] == "UNVERIFIED" and tiny["float_shares"]["status"] == "UNAVAILABLE"
    nofl = report["symbols"]["NOFL"]
    assert nofl["public_float_value"] is None and nofl["sec_filer_status"]["category"] == "Large accelerated filer"
    assert report["errors"]["ZZZZ"] == "NO_SEC_CIK" and report["errors"]["NOFL"] == "shares_outstanding:HTTP_404"
    assert all(h["User-Agent"] == "Owner Name owner@example.com" for _, h in session.calls)
    assert report["status"] == "OK" and report["schema"] == "ghazi.issuer_sizes.v2"


def test_missing_identity_and_refusal_are_reported_without_retry_loops():
    assert sizes.build(["TINY"], agent=None, now=NOW)["status"] == "SEC_IDENTITY_MISSING"
    session = Session({sizes.TICKERS_URL: Response({}, 403)})
    refused = sizes.build(["TINY"], agent="a b@c.d", session=session, now=NOW, pause=0)
    assert refused["status"] == "SEC_REFUSED_HTTP_403" and len(session.calls) == 1
    session = Session({sizes.TICKERS_URL: TICKERS, sizes.CONCEPT_URL.format(cik=111): Response({}, 429)})
    throttled = sizes.build(["TINY", "NOFL"], agent="a b@c.d", session=session, now=NOW, pause=0)
    assert throttled["errors"]["TINY"] == "public_float_value:HTTP_429" and "NOFL" not in throttled["errors"]
    assert len(session.calls) == 2  # ticker map + the throttled request, nothing after
