"""SEC latest-filings feed: official times kept, filer rows only, CIK->ticker without guessing."""
import io
from datetime import datetime, timezone

from options_radar import halt_news_engine as hne
from options_radar import sec_current_feed as scf

ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>8-K - COGENT BIOSCIENCES, INC. (0001622229) (Filer)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/1622229/x-index.htm"/>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-11-30 &lt;b&gt;AccNo:&lt;/b&gt; 1 Item 7.01: Reg FD Item 8.01: Other</summary>
<updated>2026-11-30T07:02:11-05:00</updated></entry>
<entry><title>8-K - COGENT BIOSCIENCES, INC. (0001622229) (Subject)</title><updated>2026-11-30T07:02:11-05:00</updated></entry>
<entry><title>8-K - Alphabet Inc. (0001652044) (Filer)</title><updated>2026-11-30T08:00:00-05:00</updated></entry>
<entry><title>424B5 - TINY BIO CORP (0009999999) (Filer)</title><updated>2026-11-30T09:00:00-05:00</updated></entry>
</feed>"""
REGISTRY = {"fields": ["ticker", "cik", "name", "exchange"],
            "rows": [["COGT", "0001622229", "Cogent Biosciences, Inc.", "Nasdaq"],
                     ["GOOGL", "0001652044", "Alphabet Inc.", "Nasdaq"], ["GOOG", "0001652044", "Alphabet Inc.", "Nasdaq"]]}
NOW = datetime(2026, 11, 30, 12, 3, 30, tzinfo=timezone.utc)


def test_parse_keeps_filer_rows_official_time_items_and_drops_unknown_or_ambiguous_ciks():
    events = scf.parse(ATOM, scf.cik_map(REGISTRY), NOW)
    assert [e["symbol"] for e in events] == ["COGT"]  # Alphabet: two share classes; TINY: not listed
    e = events[0]
    assert e["published"] == "2026-11-30T12:02:11+00:00" and e["first_seen"] == NOW.isoformat()
    assert e["items"] == ["7.01", "8.01"] and "إفصاح Reg FD" in e["items_ar"]


def test_no_user_agent_means_no_request():
    calls = []
    assert scf.fetch({}, opener=lambda *a, **k: calls.append(a)) == [] and calls == []


def test_fetch_and_news_event_wiring(monkeypatch):
    import json

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=20):
        url = req.full_url
        return Resp(json.dumps(REGISTRY).encode() if url == scf.REGISTRY_URL else ATOM.encode())

    events = scf.fetch({"SEC_USER_AGENT": "GhaziRadar ops@example.com"}, forms=("8-K",), opener=opener)
    assert [e["symbol"] for e in events] == ["COGT"]
    monkeypatch.setattr(scf, "fetch", lambda *a, **k: events)
    news = hne.fetch_sec_current_filings()
    assert news[0].provider == "sec_current_feed" and news[0].published == "2026-11-30T12:02:11+00:00"
