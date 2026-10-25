"""Private scan paths without waiting for a session: closed gate, broken source, stale data, success.

Synthetic fixtures only; passing here is not a live run.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from options_radar import output_policy as op
from scripts import private_market_scan as pms

NOW = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)  # Monday 11:00 New York
OWNER = {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
         "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true", "TELEGRAM_OWNER_CHAT_ID": "777", "TELEGRAM_CHAT_ID": "-100"}


class Response:
    def __init__(self, status, payload):
        self.status_code, self.payload = status, payload

    def json(self):
        return self.payload


def _bars_for(sessions, now, today_volume):
    rows = []
    for i, (open_, close) in enumerate(sessions):
        today = i == len(sessions) - 1
        t = open_
        while t < close and t + timedelta(minutes=5) <= now:
            price = 10 + 0.5 * today + (0.002 * ((t - open_).seconds // 300) if today else 0)
            rows.append({"t": t.isoformat().replace("+00:00", "Z"), "o": price, "h": price + 0.05,
                         "l": price - 0.05, "c": price, "v": today_volume if today else 100})
            t += timedelta(minutes=5)
    return rows


class Session:
    def __init__(self, movers_status=200, updated=NOW - timedelta(minutes=5)):
        self.movers_status, self.updated, self.urls = movers_status, updated, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append(url)
        if url.endswith("/movers"):
            return Response(self.movers_status, {"gainers": [{"symbol": "ABCD", "percent_change": 9.1}],
                                                 "last_updated": self.updated.isoformat()})
        if url.endswith("/most-actives"):
            return Response(200, {"most_actives": [{"symbol": "WXYZ", "volume": 1}]})
        sess = pms.sessions(NOW)
        return Response(200, {"bars": _bars_for(sess, NOW - timedelta(minutes=16), 400), "next_page_token": None})


def _private_sink(sent):
    def send(text):
        return op.deliver_private(text, sources=["alpaca_iex"], env=OWNER, get_chat=lambda c: {"type": "private"},
                                  send=lambda body, chat: sent.append((chat, body)) or SimpleNamespace(message_id=5))
    return send


def test_closed_gates_mean_no_request():
    session = Session()
    result = pms.run(NOW, {}, None, session=session)
    assert result["status"] == "NO_QUALIFIED_SOURCE" and session.urls == []
    assert [t["provider"] for t in result["providers_tried"]] == ["nasdaq_screener", "alpaca_screener"]


def test_broken_and_stale_sources_stop_before_measuring():
    broken = pms.run(NOW, OWNER, None, session=Session(movers_status=500))
    assert broken["status"] == "DISCOVERY_HTTP_500"
    stale = pms.run(NOW, OWNER, None, session=Session(updated=NOW - timedelta(hours=3)))
    assert stale["status"] == "DISCOVERY_STALE"


def test_success_path_separates_discovery_momentum_and_setup_and_stays_private():
    sent = []
    catalysts = {"watchlist": [{"symbol": "ABCD", "latest_date": "2026-10-23"}]}
    result = pms.run(NOW, OWNER, catalysts, session=Session(), send_private=_private_sink(sent))
    assert result["status"] == "MEASURED" and result["delivery"] == "DELIVERED"
    assert len(sent) == 1 and sent[0][0] == "777"
    body = sent[0][1]
    assert "سبب الظهور: ضمن الأعلى صعودًا" in body and "محفز رسمي 2026-10-23" in body
    assert "RVOL بنفس الوقت 4.0" in body and "above_prior_day_high" in body
    # the public status carries no symbols, prices or derived counts
    public = json.dumps(result)
    assert "ABCD" not in public and "WXYZ" not in public and "rvol" not in public.lower()


def test_measure_uses_completed_bars_and_same_elapsed_time():
    sess = pms.sessions(NOW)
    bars = [{**b, "t": datetime.fromisoformat(b["t"].replace("Z", "+00:00"))}
            for b in _bars_for(sess, NOW, 400)]  # includes the bar still forming
    m = pms.measure(bars, sess, NOW - timedelta(minutes=16))
    assert m["status"] == "OK" and m["last_bar_end"] <= (NOW - timedelta(minutes=16)).isoformat()
    assert m["rvol_same_time"] == 4.0 and m["above_prior_high"] is True
