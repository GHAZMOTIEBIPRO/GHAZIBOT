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


def minute_rows(base, today_volume, today_factor=1.1):
    rows = []
    for i, (open_, close) in enumerate(SESS[-11:]):
        today = i == 10
        t = open_ - timedelta(minutes=30)  # pre-market bars must be ignored
        while t < close and t + timedelta(minutes=5) <= NOW:
            price = base * (today_factor if today else 1.0)
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
    def __init__(self, assets_ok=True, snapshots_ok=True, fail_daily_batch=False, stale="NONE",
                 assets=("ABCD", "WXYZ", "OLDD"), prices=None, screener=None):
        self.assets_ok, self.snapshots_ok, self.fail_daily_batch, self.stale = assets_ok, snapshots_ok, fail_daily_batch, stale
        self.assets, self.screener = assets, screener
        self.prices = prices or {"ABCD": 11.0}
        self.calls, self.daily_symbols = [], []

    def get(self, url, params=None, headers=None, timeout=None):
        path = urlparse(url).path
        self.calls.append(path)
        if path == "/v2/assets":
            if not self.assets_ok:
                return Response(500, {})
            return Response(200, [{"symbol": s, "tradable": True, "exchange": "NASDAQ"} for s in self.assets]
                            + [{"symbol": "OTCQ", "tradable": True, "exchange": "OTC"}])
        if path.startswith("/v1beta1/screener/stocks/"):
            if self.screener is None:
                return Response(500, {})
            if path.endswith("/movers"):
                return Response(200, {"last_updated": iso(NOW - timedelta(minutes=5)), **self.screener})
            return Response(200, {"most_actives": []})
        if path == "/v2/stocks/snapshots":
            if not self.snapshots_ok:
                return Response(500, {})
            return Response(200, {s: {"dailyBar": {"v": 1}, "prevDailyBar": {"c": 10.0},
                                      "latestTrade": {"p": self.prices.get(s, 10.1), "t": iso(NOW)}}
                                  for s in params["symbols"].split(",")})
        symbols = params["symbols"].split(",")
        if params["timeframe"] == "1Day":
            self.daily_symbols.extend(symbols)
            if self.fail_daily_batch and "WXYZ" in symbols:
                return Response(500, {})
            return Response(200, {"bars": {s: daily_rows(10.0, stale=(s == self.stale)) for s in symbols},
                                  "next_page_token": None})
        factor = {s: p / 10.0 for s, p in self.prices.items()}
        return Response(200, {"bars": {s: minute_rows(10.0, 400 if s in self.prices else 100,
                                                      today_factor=factor.get(s, 1.1)) for s in symbols},
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
    assert no_assets["universe"] == {"mode": "LIMITED_LIST", "status": "ASSETS_HTTP_500", "screener": "HTTP_500"}
    assert no_assets["_private"]["coverage"]["mode"] == "LIMITED_LIST"
    no_snaps = pms.run(NOW, OWNER, None, session=Session(snapshots_ok=False))
    assert no_snaps["status"] == "MEASURED" and no_snaps["snapshots"] == "NO_SNAPSHOTS"
    assert no_snaps["_private"]["coverage"]["pick_basis"] == "liquidity only (snapshots unavailable)"


def test_a_falling_stock_is_shortlisted_and_labelled_down():
    sent = []
    session = Session(prices={"ABCD": 11.0, "DOWN": 8.8}, assets=("ABCD", "WXYZ", "DOWN"))
    result = pms.run(NOW, OWNER, None, session=session, send_private=sink(sent))
    rows = {r["symbol"]: r for r in result["_private"]["rows"]}
    assert rows["DOWN"]["direction"] == "DOWN" and rows["ABCD"]["direction"] == "UP"
    assert rows["DOWN"]["setup"]["change_at_most_minus_5pct"] is True
    assert rows["DOWN"]["setup"]["change_at_least_5pct"] is False
    body = sent[0][1]
    assert "▼ هابط" in body and "هبوط ≥ 5%" in body and "change_at" not in body  # Arabic labels, no raw keys


def test_history_is_fetched_only_for_the_largest_movers(monkeypatch):
    monkeypatch.setattr(pms, "PREFILTER", 2)
    names = tuple(f"S{i:03d}" for i in range(50))
    prices = {"S007": 12.0, "S031": 7.5}  # the two largest absolute moves, one up, one down
    session = Session(assets=names, prices=prices)
    catalysts = {"watchlist": [{"symbol": "S040", "latest_date": "2026-10-23"}]}
    result = pms.run(NOW, OWNER, catalysts, session=session)
    assert sorted(set(session.daily_symbols)) == ["S007", "S031", "S040"]  # movers + catalyst, not all 50
    assert result["_private"]["coverage"]["history_requested"] == 3
    assert result["_private"]["coverage"]["with_snapshots"] == 50
    assert set(result["stage_seconds"]) == {"universe", "snapshots", "daily_history", "intraday_bars"}


def test_limited_list_adds_screener_gainers_and_losers():
    screener = {"gainers": [{"symbol": "UPPP", "percent_change": 12.0}],
                "losers": [{"symbol": "DNNN", "percent_change": -9.0}]}
    result = pms.run(NOW, OWNER, None, session=Session(assets_ok=False, screener=screener))
    assert result["universe"]["screener"] == "OK"
    assert result["_private"]["coverage"]["universe"] == len(pms.LIMITED_LIST) + 2


def test_a_failed_batch_is_reported_and_the_rest_continues():
    pms_batch = pms.run(NOW, OWNER, None, session=Session(fail_daily_batch=True))
    # 3 symbols in one batch of 100: the failing batch carries all, so nothing liquid remains
    assert pms_batch["status"] in ("DAILY_ALL_BATCHES_FAILED", "NO_MEASURABLE_CANDIDATES")
    assert pms_batch["daily_batches"]["failed"] >= 1
