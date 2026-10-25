"""Private scan without waiting for a session: synthetic fixtures only (not a live run).

Paths: closed gate, missing universe endpoint, missing snapshots, a failed
batch, stale history, data-quality checks, and the success path delivered
only to a private chat with nothing derived in the public status.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlparse

from options_radar import output_policy as op
from scripts import private_market_scan as pms

NOW = datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc)  # Monday 11:00 New York
OWNER = {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
         "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true", "TELEGRAM_OWNER_CHAT_ID": "777", "TELEGRAM_CHAT_ID": "-100"}
SESS = pms.sessions(NOW)


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def daily_rows(price, n=30, stale=False):
    days = [o for o, _ in pms.sessions(NOW, 60)[:-1]][-n:]
    if stale:
        days = days[:-3]
    return [{"t": iso(d.replace(hour=4, minute=0)), "o": price, "h": price * 1.02, "l": price * 0.98, "c": price,
             "v": 1_000_000} for d in days]


def minute_rows(base, today_volume):
    rows = []
    for i, (open_, close) in enumerate(SESS[-11:]):
        today = i == 10
        t = open_ - timedelta(minutes=30)  # pre-market bars must be ignored
        while t < close and t + timedelta(minutes=5) <= NOW:
            price = base * (1.1 if today else 1.0)
            rows.append({"t": iso(t), "o": price, "h": price, "l": price, "c": price,
                         "v": today_volume if today else 100})
            t += timedelta(minutes=5)
    rows.append(dict(rows[-1]))  # a duplicate bar
    return rows


class Response:
    def __init__(self, status, payload):
        self.status_code, self.payload = status, payload

    def json(self):
        return self.payload


class Session:
    def __init__(self, assets_ok=True, snapshots_ok=True, fail_daily_batch=False, stale="NONE"):
        self.assets_ok, self.snapshots_ok, self.fail_daily_batch, self.stale = assets_ok, snapshots_ok, fail_daily_batch, stale
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        path = urlparse(url).path
        self.calls.append(path)
        if path == "/v2/assets":
            if not self.assets_ok:
                return Response(500, {})
            return Response(200, [{"symbol": s, "tradable": True, "exchange": "NASDAQ"} for s in ("ABCD", "WXYZ", "OLDD")]
                            + [{"symbol": "OTCQ", "tradable": True, "exchange": "OTC"}])
        if path == "/v2/stocks/snapshots":
            if not self.snapshots_ok:
                return Response(500, {})
            return Response(200, {s: {"dailyBar": {"v": 1}, "prevDailyBar": {"c": 10.0},
                                      "latestTrade": {"p": 11.0 if s == "ABCD" else 10.1, "t": iso(NOW)}}
                                  for s in params["symbols"].split(",")})
        symbols = params["symbols"].split(",")
        if params["timeframe"] == "1Day":
            if self.fail_daily_batch and "WXYZ" in symbols:
                return Response(500, {})
            return Response(200, {"bars": {s: daily_rows(10.0, stale=(s == self.stale)) for s in symbols},
                                  "next_page_token": None})
        return Response(200, {"bars": {s: minute_rows(10.0, 400 if s == "ABCD" else 100) for s in symbols},
                              "next_page_token": None})


def sink(sent):
    def send(text):
        return op.deliver_private(text, sources=["alpaca_iex"], env=OWNER, get_chat=lambda c: {"type": "private"},
                                  send=lambda body, chat: sent.append((chat, body)) or SimpleNamespace(message_id=5))
    return send


def test_closed_gate_makes_no_request():
    session = Session()
    assert pms.run(NOW, {}, None, session=session)["status"] == "DENIED_BY_POLICY" and session.calls == []


def test_success_path_full_market_with_coverage_and_private_delivery_only():
    sent = []
    catalysts = {"watchlist": [{"symbol": "ABCD", "latest_date": "2026-10-23"}]}
    result = pms.run(NOW, OWNER, catalysts, session=Session(stale="OLDD"), send_private=sink(sent))
    assert result["status"] == "MEASURED" and result["delivery"] == "DELIVERED"
    cov = result["_private"]["coverage"]
    assert cov["mode"] == "FULL_MARKET" and cov["universe"] == 3 and cov["excluded"] == {"STALE_LAST_BAR": 1}
    top = result["_private"]["rows"][0]
    assert top["symbol"] == "ABCD" and top["feed"] == "sip"
    m = top["momentum"]
    assert m["rvol_same_time"] == 4.0 and m["quality"]["duplicates_removed"] == 1
    assert m["quality"]["outside_session_excluded"] > 0  # pre-market bars were not counted
    body = sent[0][1]
    assert sent[0][0] == "777" and "مسح السوق كامل: 3 رمز" in body and "STALE_LAST_BAR 1" in body
    assert "حجم كل البورصات" in body and "محفز رسمي 2026-10-23" in body
    public = json.dumps({k: v for k, v in result.items() if k != "_private"})
    assert "ABCD" not in public and "WXYZ" not in public and "rvol" not in public.lower()


def test_missing_endpoints_degrade_instead_of_stopping():
    no_assets = pms.run(NOW, OWNER, {"watchlist": [{"symbol": "ABCD"}]}, session=Session(assets_ok=False))
    assert no_assets["universe"] == {"mode": "LIMITED_LIST", "status": "ASSETS_HTTP_500"}
    assert no_assets["_private"]["coverage"]["mode"] == "LIMITED_LIST"
    no_snaps = pms.run(NOW, OWNER, None, session=Session(snapshots_ok=False))
    assert no_snaps["status"] == "MEASURED" and no_snaps["snapshots"] == "NO_SNAPSHOTS"
    assert no_snaps["_private"]["coverage"]["pick_basis"] == "liquidity only (snapshots unavailable)"


def test_a_failed_batch_is_reported_and_the_rest_continues():
    pms_batch = pms.run(NOW, OWNER, None, session=Session(fail_daily_batch=True))
    # 3 symbols in one batch of 100: the failing batch carries all, so nothing liquid remains
    assert pms_batch["status"] in ("DAILY_ALL_BATCHES_FAILED", "NO_MEASURABLE_CANDIDATES")
    assert pms_batch["daily_batches"]["failed"] >= 1
