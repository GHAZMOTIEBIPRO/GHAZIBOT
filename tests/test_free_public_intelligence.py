from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import requests

from options_radar.free_public_intelligence import (
    ALPACA_LATEST,
    BLS_ICS,
    FED_MONETARY,
    GDELT_DOC,
    YAHOO_FINANCE_RSS,
    yahoo_rss_attention,
    alpaca_iex_health,
    build_context,
    fed_monetary_updates,
    gdelt_attention,
    parse_bls_calendar,
)
from scripts.send_free_macro_reminders import (
    format_macro_message,
    select_macro_reminders,
    send_from_file,
)

NOW = datetime(2026, 10, 14, 13, 15, tzinfo=timezone.utc)
ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:cpi
SUMMARY:Consumer Price 
 Index for September 2026
DTSTART;TZID=US-Eastern:20261014T103000
END:VEVENT
BEGIN:VEVENT
UID:jolts
SUMMARY:Job Openings and Labor Turnover Survey
DTSTART;TZID=America/New_York:20261014T100000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Historical Consumer Price Index
DTSTART;TZID=America/New_York:20260814T083000
END:VEVENT
END:VCALENDAR
"""
FED = b"""<?xml version="1.0"?><rss><channel>
<item><title>Federal Reserve policy statement</title>
<link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20261014a.htm</link>
<pubDate>Wed, 14 Oct 2026 12:00:00 GMT</pubDate></item>
</channel></rss>"""


class Response:
    def __init__(self, *, content=b"", json_value=None):
        self.content = content
        self.text = content.decode("utf-8")
        self.value = json_value

    def raise_for_status(self):
        return None

    def json(self):
        return self.value


class Session:
    def __init__(self, sources):
        self.sources = sources
        self.calls = []

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append((url, params or {}, headers or {}, timeout))
        answer = self.sources.get(url)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise requests.ConnectionError("not available")
        return answer


def test_bls_folded_ical_and_ny_dst_are_not_fake_current_events():
    items = parse_bls_calendar(ICS, now=NOW)
    assert len(items) == 2
    assert items[0]["title"] == "Job Openings and Labor Turnover Survey"
    assert items[0]["scheduled_at"] == "2026-10-14T14:00:00+00:00"
    assert items[1]["title"] == "Consumer Price Index for September 2026"
    assert items[1]["scheduled_at"] == "2026-10-14T14:30:00+00:00"
    assert items[0]["economic_result_available"] is False


def test_invalid_ical_fails_closed():
    import pytest

    with pytest.raises(ValueError):
        parse_bls_calendar("<html>blocked</html>", now=NOW)


def test_gdelt_only_explicit_exchange_symbol_and_never_market_signal():
    session = Session({
        GDELT_DOC: Response(json_value={"articles": [
            {"title": "NASDAQ:MU shares rally after results", "url": "https://press.test/story",
             "seendate": "20261014T121500Z"},
            {"title": "MU may mean many things", "url": "https://press.test/ambiguous",
             "seendate": "20261014T121500Z"},
            {"title": "$MU stock falls", "url": "https://press.test/old",
             "seendate": "20261011T121500Z"},
            {"title": "$MU stock", "url": "javascript:alert(1)",
             "seendate": "20261014T121500Z"},
        ]}),
    })
    rows = gdelt_attention(["MU"], session=session, now=NOW)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "MU"
    assert rows[0]["authority"] == "ATTENTION_ONLY"
    assert rows[0]["market_direction"] == "UNKNOWN"
    assert rows[0]["independent_confirmation"] is False
    assert session.calls[0][1]["mode"] == "artlist"
    assert session.calls[0][3] <= 15


def test_fed_rss_rfc_timestamp_is_publication_not_calendar():
    session = Session({FED_MONETARY: Response(content=FED)})
    rows = fed_monetary_updates(session=session, now=NOW)
    assert len(rows) == 1
    assert rows[0]["published_at"] == "2026-10-14T12:00:00+00:00"
    assert rows[0]["event_type"] == "RELEASED_NEWS"
    assert rows[0]["price_direction"] == "UNKNOWN"


def test_alpaca_absent_keys_never_calls_provider(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    session = Session({})
    result = alpaca_iex_health(session=session, now=NOW)
    assert result["status"] == "NOT_CONFIGURED"
    assert result["execution_grade"] is False
    assert session.calls == []


def test_alpaca_iex_latest_bar_keeps_entitlement_non_executable():
    session = Session({
        ALPACA_LATEST: Response(
            content=b'{"bar":{"t":"2026-10-14T13:14:00Z","c":100}}',
            json_value={"bar": {"t": "2026-10-14T13:14:00Z", "c": 100}},
        ),
    })
    result = alpaca_iex_health(session=session, now=NOW, key="id", secret="secret")
    assert result["status"] == "AVAILABLE_RESEARCH"
    assert result["bar_timestamp"] == "2026-10-14T13:14:00+00:00"
    assert result["execution_grade"] is False and result["opra_options"] is False
    assert result["quote_freshness_verified"] is False
    assert session.calls[0][1] == {"feed": "iex"}


def test_sources_fail_independently_without_ever_promoting_news(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    session = Session({
        GDELT_DOC: requests.ConnectionError("rate limited"),
        FED_MONETARY: Response(content=FED),
        BLS_ICS: Response(content=ICS.encode()),
    })
    context = build_context(symbols=["MU"], session=session, now=NOW)
    assert context["status"] == "DEGRADED"
    assert context["gdelt_attention"] == []
    assert len(context["fed_monetary"]) == 1
    assert len(context["bls_upcoming"]) == 2
    assert context["decision_authority"] is False
    assert context["source_errors"]["gdelt_attention"].startswith("ConnectionError")


def test_macro_reminders_are_deduped_and_reject_stale_context(tmp_path):
    context = {
        "generated_at": NOW.isoformat(),
        "bls_upcoming": [
            {
                "title": "Employment Situation for September 2026",
                "scheduled_at": (NOW + timedelta(minutes=60)).isoformat(),
                "source": "bls_official_ical", "authority": "OFFICIAL_SCHEDULE",
                "economic_result_available": False,
            },
        ],
    }
    path = tmp_path / "public.json"
    state = tmp_path / "state.json"
    import json

    path.write_text(json.dumps(context), encoding="utf-8")
    sent = []
    receipt = lambda message: sent.append(message) or SimpleNamespace(message_id=42)
    outcome = send_from_file(path, state, now=NOW, send=receipt)
    assert outcome["sent"] == 1
    assert "CALL" in sent[0] and "ليست إشارة" in sent[0]
    assert len(json.loads(state.read_text(encoding="utf-8"))["macro_sent"]) == 1
    assert send_from_file(path, state, now=NOW, send=receipt)["sent"] == 0
    assert len(sent) == 1
    stale = {**context, "generated_at": (NOW - timedelta(hours=1)).isoformat()}
    assert select_macro_reminders(stale, {}, now=NOW) == []
    assert "10:30" not in format_macro_message(context["bls_upcoming"][0])


def test_no_unverified_macro_or_post_release_notifies():
    row = {
        "title": "CPI", "source": "random_rss",
        "scheduled_at": (NOW + timedelta(minutes=30)).isoformat(),
        "authority": "ATTENTION_ONLY", "economic_result_available": False,
    }
    data = {"generated_at": NOW.isoformat(), "bls_upcoming": [row]}
    assert select_macro_reminders(data, {}, now=NOW) == []
    row["source"] = "bls_official_ical"
    row["authority"] = "OFFICIAL_SCHEDULE"
    row["scheduled_at"] = (NOW - timedelta(minutes=1)).isoformat()
    assert select_macro_reminders(data, {}, now=NOW) == []


def test_gdelt_429_is_explicit_and_never_retried_or_fake_articles():
    from types import SimpleNamespace

    refusal = requests.HTTPError("429 rejected", response=SimpleNamespace(status_code=429))
    session = Session({
        GDELT_DOC: refusal,
        FED_MONETARY: Response(content=FED),
        BLS_ICS: Response(content=ICS.encode()),
    })
    context = build_context(symbols=["MU"], session=session, now=NOW)
    assert context["status"] == "DEGRADED"
    assert context["source_errors"]["gdelt_attention"] == "HTTP_429"
    assert context["gdelt_attention"] == []
    assert sum(url == GDELT_DOC for url, *_ in session.calls) == 1
    assert len(context["bls_upcoming"]) == 2


def test_single_bounded_gdelt_query_covers_12_explicit_smallcap_symbols():
    watch=["RGC","BNAI","RKLB","SOUN","ASTS","IONQ","MU","NVDA","AMD","AAPL","TSLA","PLTR"]
    session=Session({GDELT_DOC:Response(json_value={"articles":[]})})
    output=gdelt_attention(watch,session=session,now=NOW)
    assert output==[]
    assert len(session.calls)==1
    params=session.calls[0][1]
    assert '"PLTR"' in params["query"]
    assert '"RGC"' in params["query"]
    assert params["maxrecords"]==75

def test_yahoo_finance_rss_safely_extracts_ticker_tagged_stories_only():
    xml = b'''<?xml version="1.0"?><rss version="2.0"><channel>
      <title>Yahoo Finance headlines</title>
      <item><title>Rocket Lab (RKLB) announces satellite milestone</title>
        <link>https://finance.yahoo.com/news/rocket-lab-example</link>
        <pubDate>Wed, 14 Oct 2026 12:00:00 GMT</pubDate></item>
      <item><title>Unrelated research update</title>
        <link>https://finance.yahoo.com/news/unrelated</link>
        <pubDate>Wed, 14 Oct 2026 12:00:00 GMT</pubDate></item>
    </channel></rss>'''
    s = Session({YAHOO_FINANCE_RSS: Response(content=xml)})
    items = yahoo_rss_attention(["RKLB","MU"],session=s,now=NOW)
    assert len(items)==1
    assert items[0]["symbol"]=="RKLB"
    assert items[0]["source"]=="yahoo_finance_rss"
    assert items[0]["authority"]=="ATTENTION_ONLY"
    assert items[0]["independent_confirmation"] is False
    assert items[0]["official_confirmed"] is False
    assert items[0]["market_direction"]=="UNKNOWN"
    assert items[0]["published_at_reported"]=="2026-10-14T12:00:00+00:00"
    assert len(s.calls)==1


def test_yahoo_rss_does_not_assign_ambiguous_titles_to_requested_symbol():
    xml = b'''<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>Potential partnership for biotechnology sector</title>
        <link>https://finance.yahoo.com/news/sector-example</link>
        <pubDate>Wed, 14 Oct 2026 12:00:00 GMT</pubDate></item>
    </channel></rss>'''
    session = Session({YAHOO_FINANCE_RSS: Response(content=xml)})
    assert yahoo_rss_attention(["RGC"],session=session,now=NOW)==[]


def test_yahoo_rss_rejection_is_diagnostic_not_invented_news():
    rejected = requests.HTTPError("429",response=SimpleNamespace(status_code=429))
    session=Session({
        GDELT_DOC:Response(json_value={"articles":[]}),
        YAHOO_FINANCE_RSS:rejected,
        FED_MONETARY:Response(content=FED),
        BLS_ICS:Response(content=ICS.encode()),
    })
    result=build_context(symbols=["RKLB"],session=session,now=NOW)
    assert result["yahoo_rss_attention"] == []
    assert result["source_errors"]["yahoo_rss_attention"]=="HTTP_429"
    assert result["status"]=="DEGRADED"
    assert len([x for x in session.calls if x[0]==YAHOO_FINANCE_RSS])==1

