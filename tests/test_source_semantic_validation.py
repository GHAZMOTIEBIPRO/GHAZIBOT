"""An endpoint is not healthy simply because HTTP returned 200."""
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from options_radar import free_data_health as health
from options_radar.source_payload_validation import validate_source_payload as validate

NOW = datetime(2026, 10, 19, 10, tzinfo=timezone.utc)


def sample(role, body, content_type="application/json"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    return validate({"role": role}, data, content_type, now=NOW)


def test_sec_200_html_or_wrong_identity_cannot_be_healthy():
    valid = {"cik": 320193, "filings": {"recent": {"form": []}}}
    assert sample("identity_and_filings_fallback", valid)["ok"] is True
    assert sample("identity_and_filings_fallback", {**valid, "cik": 320194})["ok"] is False
    assert sample("identity_and_filings_fallback", b"<html>Denied</html>")["ok"] is False
    assert sample("fundamentals_and_share_history", {"cik": 320193, "facts": {"us-gaap": {}}})["ok"]
    assert not sample("fundamentals_and_share_history", {"cik": 320193, "facts": {}})["ok"]


def test_occ_documentation_never_counts_as_real_options_market_data():
    report = sample("options_volume_context_contract", b"<html>OCC docs</html>", "text/html")
    assert report == {"ok": False, "content_status": "DOCUMENTATION_ONLY_NO_DATA"}


def test_finra_success_requires_dated_real_json_data():
    role = "daily_short_sale_volume_context"
    good = [{"tradeReportDate": "2026-10-16",
             "totalParQuantity": 123456, "shortParQuantity": 3000}]
    assert sample(role, good)["ok"] is True
    assert sample(role, b"Permission denied", "text/plain")["content_status"] == "FINRA_NON_JSON_RESPONSE"
    assert sample(role, [], "application/json")["ok"] is False
    stale = [{**good[0], "tradeReportDate": "2026-09-01"}]
    assert sample(role, stale)["ok"] is False
    forged = [{**good[0], "totalParQuantity": 0}]
    assert sample(role, forged)["ok"] is False


def test_github_gamma_is_research_only_and_must_have_fresh_source_date():
    role = "gamma_cross_validation"
    good = {"date": "2026-10-16", "spot": 7500.4, "net_gex_dollars": -1e9}
    assert sample(role, good)["content_status"] == "DATED_GAMMA_RESEARCH_ONLY"
    assert sample(role, good)["source_observation_date"] == "2026-10-16"
    assert sample(role, {**good, "date": "2026-09-01"})["ok"] is False
    assert sample(role, {**good, "date": "2026-10-20"})["ok"] is False
    assert sample(role, {**good, "spot": -10})["ok"] is False
    assert sample(role, {"spot": 7500})["ok"] is False


def test_gamma_archive_stale_and_missing_price_fails_closed():
    role = "gamma_history_validation"
    def archive(day, spot):
        f = io.StringIO()
        writer = csv.DictWriter(f, fieldnames=["date", "spot", "net_0dte_gex"])
        writer.writeheader()
        writer.writerow({"date": day, "spot": spot, "net_0dte_gex": 10000})
        return f.getvalue().encode()
    assert sample(role, archive("2026-10-16", 7512), "text/plain")["ok"]
    assert not sample(role, archive("2026-10-01", 7512), "text/plain")["ok"]
    assert not sample(role, archive("2026-10-16", ""), "text/plain")["ok"]


def test_treasury_must_contain_actual_yield_observations():
    role = "macro_context"
    real = b"<feed xmlns:d='urn:dummy'><entry><d:NEW_DATE>2026-10-16</d:NEW_DATE><d:BC_10YEAR>4.1</d:BC_10YEAR></entry></feed>"
    assert sample(role, real, "application/xml")["ok"] is True
    assert sample(role, b"<html>Webpage</html>", "text/html")["ok"] is False
    assert sample(role, b"not xml", "text/html")["ok"] is False


def test_direct_health_check_has_semantic_gate_even_with_http_200(monkeypatch):
    source = {"name": "FINRA test", "family": "finra", "authority": "official",
              "role": "daily_short_sale_volume_context", "method": "POST_FINRA",
              "url": "https://example.test"}
    class Response:
        status = 200
        headers = {"Content-Type": "text/plain"}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, amount):
            return b"temporary error"
    monkeypatch.setattr(health.urllib.request, "urlopen", lambda request, timeout: Response())
    item = health.check(source)
    assert item["status"] == 200 and item["transport_reachable"] is True
    assert item["ok"] is False
    assert item["content_status"] == "FINRA_NON_JSON_RESPONSE"


def test_source_dashboard_uses_verified_status_and_clocks():
    page = Path("public/index.html").read_text(encoding="utf-8")
    app = Path("public/terminal-hub.js").read_text(encoding="utf-8")
    css = Path("public/terminal-hub.css").read_text(encoding="utf-8")
    assert 'id="terminal-panel-trust"' in page
    assert 'data-terminal-tab="trust"' in page
    assert 'id="terminal-trust-summary"' in page
    assert 'id="terminal-trust-grid"' in page
    assert "bot-state/runtime/public/data/free_data_health.json" in app
    assert "bot-state/runtime/public/data/data-status.json" in app
    assert "http_success_is_not_data_success" in app
    assert "transport_reachable===true" in app
    assert "function renderTrust()" in app
    assert "terminal-trust-grid" in css
