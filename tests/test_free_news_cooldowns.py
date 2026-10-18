"""Free news cooldowns: avoid hammering public feeds, never invent coverage."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import requests

import options_radar.free_public_intelligence as news

NOW = datetime(2026, 10, 18, 16, tzinfo=timezone.utc)


class Response:
    content = b'<rss version="2.0"><channel></channel></rss>'

    def raise_for_status(self):
        return None


class Session:
    def __init__(self, refuse=True):
        self.calls = []
        self.refuse = refuse

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append(url)
        if self.refuse:
            code = (429 if url == news.GDELT_DOC else
                    404 if url == news.PRESS_WIRE_RSS["prnewswire"] else
                    403 if url == news.PRESS_WIRE_RSS["globenewswire"] else
                    None)
            if code is not None:
                raise requests.HTTPError(str(code),
                                         response=SimpleNamespace(status_code=code))
        return Response()


def quiet_official_feeds(monkeypatch):
    monkeypatch.setattr(news, "fed_monetary_updates", lambda **kwargs: [])
    monkeypatch.setattr(news, "bls_upcoming", lambda **kwargs: [])


def test_source_refusals_create_durable_per_provider_circuits(monkeypatch):
    quiet_official_feeds(monkeypatch)
    first = Session()
    report = news.build_context(symbols=["RKLB"], session=first, now=NOW)
    assert report["status"] == "DEGRADED"
    assert report["source_errors"]["gdelt_attention"] == "HTTP_429"
    assert report["source_errors"]["press_wire_prnewswire"] == "HTTP_404"
    assert report["source_errors"]["press_wire_globenewswire"] == "HTTP_403"
    assert len([x for x in first.calls if x == news.GDELT_DOC]) == 1
    assert report["source_cooldowns"]["gdelt_attention"]["last_error"] == "HTTP_429"
    assert report["source_cooldowns"]["press_wire_prnewswire"]["last_error"] == "HTTP_404"
    assert report["source_cooldowns"]["press_wire_globenewswire"]["last_error"] == "HTTP_403"
    second = Session()
    start = NOW + timedelta(hours=1)
    active = news.valid_source_cooldowns(report, now=start)
    refreshed = news.build_context(
        symbols=["RKLB"], now=start, session=second, prior_cooldowns=active,
    )
    assert news.GDELT_DOC not in second.calls
    assert news.PRESS_WIRE_RSS["prnewswire"] not in second.calls
    assert news.PRESS_WIRE_RSS["globenewswire"] not in second.calls
    assert news.GOOGLE_NEWS_RSS in second.calls
    assert refreshed["source_errors"]["gdelt_attention"] == "COOLDOWN_ACTIVE"
    assert refreshed["source_cooldowns"]["gdelt_attention"]["retry_after"] == (
        NOW + timedelta(hours=12)).isoformat()
    assert refreshed["decision_authority"] is False


def test_retry_after_expiry_recovers_without_manual_intervention(monkeypatch):
    quiet_official_feeds(monkeypatch)
    first = news.build_context(symbols=["RKLB"], now=NOW, session=Session())
    forty_nine = NOW + timedelta(hours=49)
    circuits = news.valid_source_cooldowns(first, now=forty_nine)
    assert circuits == {}
    recovered_session = Session(refuse=False)
    report = news.build_context(
        symbols=["RKLB"], now=forty_nine, session=recovered_session,
        prior_cooldowns=circuits,
    )
    assert report["source_errors"] == {}
    assert report["source_cooldowns"] == {}
    assert news.GDELT_DOC in recovered_session.calls
    assert news.PRESS_WIRE_RSS["prnewswire"] in recovered_session.calls
    assert news.PRESS_WIRE_RSS["globenewswire"] in recovered_session.calls


def test_malformed_or_future_cooldowns_do_not_disable_sources():
    good = {
        "schema": "free_public_intelligence_v1",
        "generated_at": NOW.isoformat(),
        "source_cooldowns": {
            "gdelt_attention": {
                "last_error": "HTTP_429",
                "retry_after": (NOW + timedelta(hours=10)).isoformat(),
            },
            "fake_source": {
                "last_error": "HTTP_429",
                "retry_after": (NOW + timedelta(hours=10)).isoformat(),
            },
        },
    }
    assert list(news.valid_source_cooldowns(good, now=NOW)) == ["gdelt_attention"]
    good["source_cooldowns"]["gdelt_attention"]["retry_after"] = (
        NOW + timedelta(days=99)).isoformat()
    assert news.valid_source_cooldowns(good, now=NOW) == {}
    good["generated_at"] = (NOW + timedelta(days=1)).isoformat()
    assert news.valid_source_cooldowns(good, now=NOW) == {}


def test_news_ui_discloses_cooldown_failure_as_research_only():
    script = Path("public/terminal-hub.js").read_text(encoding="utf-8")
    assert "source_cooldowns" in script
    assert "COOLDOWN_ACTIVE" in Path(
        "options_radar/free_public_intelligence.py"
    ).read_text(encoding="utf-8")
