"""Production access evidence is independently checked, never inferred from Vercel READY."""
import json
from datetime import datetime, timezone
from email.message import Message
from urllib.error import HTTPError, URLError

from scripts.check_production_access import (
    PAGES,
    SCHEMA,
    audit,
    check_site,
    check_telegram,
)

NOW = datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc)


class Response:
    def __init__(self, url, *, code=200, mime="text/html", body=b"GHAZI RADAR",
                 final=None):
        self.status = code
        self.url = final or url
        self.headers = Message()
        self.headers["Content-Type"] = mime
        self.payload = body

    def geturl(self):
        return self.url

    def read(self, max_bytes):
        return self.payload[:max_bytes]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def good(request, **kwargs):
    url = request.full_url
    assert kwargs["timeout"] <= 14
    if "api.telegram.org" in url:
        return Response(url, mime="application/json",
                        body=b'{"ok":true,"result":{"is_bot":true,"username":"REDACTED"}}')
    if "/health" in url:
        return Response(url, mime="application/json",
                        body=b'{"status":"degraded","service":"GHAZIBOT"}')
    if "/data-status" in url:
        return Response(url, mime="application/json",
                        body=b'{"status":"degraded"}')
    if "github-projects" in url:
        return Response(url, body=b'<title>50 projects</title>')
    if "catalyst-desk" in url:
        return Response(url, body='<title>GHAZI RADAR — Official Catalyst Desk</title>'.encode("utf-8"))
    return Response(url, body=b'<h1>GHAZI RADAR</h1>')


def test_external_pages_and_bot_auth_can_succeed_without_price_claims():
    report = audit(now=NOW, token="111:secret-test-token", fetch=good)
    assert report["schema"] == SCHEMA
    assert report["status"] == "ACCESSIBLE"
    assert report["site_http_accessible"] is True
    assert report["bot_api_authenticated"] is True
    assert report["telegram_delivery_verified_by_this_check"] is False
    assert report["market_data_authority"] is False
    assert report["options_execution_authority"] is False
    assert len(report["pages"]) == len(PAGES) == 6
    assert all(x["http_status"] == 200 for x in report["pages"])
    assert "secret-test-token" not in json.dumps(report)


def test_site_redirects_to_other_domains_are_rejected():
    def redirected(req, **kwargs):
        if "github-projects" in req.full_url:
            return Response(req.full_url, final="https://evil.example/fake",
                            body=b"50 projects")
        return good(req, **kwargs)

    out = check_site(fetch=redirected)
    assert next(x for x in out if x["key"] == "github_50")["result"] == (
        "WRONG_DESTINATION_OR_HTTP"
    )
    assert all(x["result"] == "ACCESSIBLE" for x in out if x["key"] != "github_50")


def test_html_error_page_or_old_stub_cannot_pass_as_site_health():
    def invalid(req, **kwargs):
        if req.full_url.endswith("/health"):
            return Response(req.full_url, mime="text/html",
                            body=b"<html>please sign in</html>")
        if "catalyst-desk" in req.full_url:
            return Response(req.full_url, body=b"<title>not deployed</title>")
        return good(req, **kwargs)

    rows = check_site(fetch=invalid)
    assert next(r for r in rows if r["key"] == "site_health")["result"] == "WRONG_CONTENT_TYPE"
    assert next(r for r in rows if r["key"] == "catalyst_desk")["result"] == "CONTENT_MISMATCH"
    assert audit(now=NOW, token="111:abc", fetch=invalid)["status"] == "SITE_HTTP_PROBE_FAILED"


def test_missing_bot_token_never_counts_as_authenticated():
    bot = check_telegram("", fetch=good)
    assert bot["result"] == "TOKEN_NOT_CONFIGURED"
    assert bot["bot_api_authenticated"] is False
    assert check_telegram("invalid/token", fetch=good)["result"] == "INVALID_TOKEN_FORMAT"


def test_bad_telegram_response_never_claims_success():
    def wrong(req, **kwargs):
        if "api.telegram.org" in req.full_url:
            return Response(req.full_url, mime="application/json",
                            body=b'{"ok":false,"result":{"is_bot":false}}')
        return good(req, **kwargs)

    status = check_telegram("111:abc", fetch=wrong)
    assert status["result"] == "NOT_VERIFIED"
    assert status["message_delivery_proven"] is False


def test_network_and_http_errors_are_sanitized_no_secret_echo():
    def broken(req, **kwargs):
        if "api.telegram.org" in req.full_url:
            raise URLError("secret-looking-token")
        if "github-projects" in req.full_url:
            raise HTTPError(req.full_url, 403, "forbidden", {}, None)
        return good(req, **kwargs)

    out = audit(now=NOW, token="123:secret-looking-token", fetch=broken)
    assert out["status"] == "SITE_HTTP_PROBE_FAILED"
    assert out["bot"]["result"] == "NOT_VERIFIED"
    assert "secret-looking-token" not in json.dumps(out)
    assert next(r for r in out["pages"] if r["key"] == "github_50")["http_status"] == 403


def test_probe_workflow_single_writer_and_explicit_failure():
    from pathlib import Path

    import yaml

    text = Path(".github/workflows/production-access-proof.yml").read_text()
    workflow = yaml.safe_load(text)
    assert workflow[True]["schedule"] == [{"cron": "20 5,14 * * 1-5"}]
    assert "state/runtime/public/data/production_access_health.json" in text
    assert "git push origin HEAD:bot-state" in text
    assert "echo $TELEGRAM_BOT_TOKEN" not in text
    assert "getMe" not in text  # Bot identity is probed in the safe Python module.
    assert "site_http_accessible" in text
    assert "bot_api_authenticated" in text
    assert "contents: write" in text
