"""GHAZI RADAR PRO platform alpha: auth, isolation, entitlements, rights gate, billing."""
from __future__ import annotations

import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ghazi_platform import backtest, rights
from ghazi_platform.config import Config
from ghazi_platform.db import Database
from ghazi_platform.security import hash_password, sign, verify_password
from ghazi_platform.web import App

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "correct-horse-42"


class Client:
    """Minimal WSGI test client that keeps cookies and the CSRF token."""

    def __init__(self, app: App, ip: str = "10.0.0.1"):
        self.app, self.ip, self.cookie, self.csrf = app, ip, "", None

    def call(self, method: str, path: str, body=None, *, headers=None, raw: bytes | None = None,
             csrf: bool = True):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        path, _, query = path.partition("?")
        env = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": query, "REMOTE_ADDR": self.ip,
               "HTTP_HOST": "platform.test", "CONTENT_LENGTH": str(len(data)), "wsgi.input": io.BytesIO(data),
               "CONTENT_TYPE": "application/json" if (body is not None or raw is not None) else "",
               "HTTP_COOKIE": self.cookie}
        if csrf and self.csrf:
            env["HTTP_X_CSRF_TOKEN"] = self.csrf
        for k, v in (headers or {}).items():
            env["HTTP_" + k.upper().replace("-", "_")] = v
        captured = {}

        def start_response(status, hdrs):
            captured["status"] = int(status.split()[0])
            captured["headers"] = hdrs

        out = b"".join(self.app(env, start_response))
        for k, v in captured["headers"]:
            if k == "Set-Cookie":
                self.cookie = v.split(";")[0]
        try:
            payload = json.loads(out)
        except ValueError:
            payload = out
        return captured["status"], payload, dict(captured["headers"])

    def signup(self, email: str, password: str = PASSWORD):
        st, body, _ = self.call("POST", "/api/auth/register", {"email": email, "password": password, "consent": True})
        assert st == 201, body
        st, body, _ = self.call("POST", "/api/auth/login", {"email": email, "password": password})
        assert st == 200, body
        self.csrf = body["csrf_token"]
        return body


@pytest.fixture
def app(tmp_path):
    cfg = Config(enabled=True, db_path=str(tmp_path / "p.sqlite3"), secure_cookies=True, dev_mode=True,
                 billing_mode="sandbox", billing_webhook_secret="whsec_test",
                 admin_emails=frozenset({"owner@example.com"}))
    return App(cfg)


def daily_csv(n: int = 260, start: float = 100.0, seed_step: float = 0.37) -> str:
    rows = ["date,open,high,low,close,volume"]
    d = date(2025, 1, 6)
    price = start
    i = 0
    while i < n:
        if d.weekday() < 5:
            wave = ((i * seed_step) % 7) - 3.2
            o = price
            c = max(1.0, price + wave * 0.6 + (0.15 if (i // 40) % 2 == 0 else -0.12))
            h, lo = max(o, c) + 0.8, min(o, c) - 0.8
            rows.append(f"{d.isoformat()},{o:.2f},{h:.2f},{lo:.2f},{c:.2f},{1000 + i}")
            price = c
            i += 1
        d += timedelta(days=1)
    return "\n".join(rows)


# ---------------------------------------------------------------- feature flag

def test_platform_is_off_without_flag(tmp_path):
    app = App(Config(enabled=False, db_path=str(tmp_path / "x.sqlite3")))
    st, body, _ = Client(app).call("GET", "/api/health")
    assert st == 404 and body == b"Not Found"


def test_static_shell_and_security_headers(app):
    st, body, headers = Client(app).call("GET", "/")
    assert st == 200 and b'dir="rtl"' in body
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY" and headers["Cache-Control"] == "no-store"
    assert Client(app).call("GET", "/static/../web.py")[0] == 404


# ---------------------------------------------------------------- auth

def test_password_hash_roundtrip():
    stored = hash_password(PASSWORD)
    assert stored.startswith("scrypt$") and PASSWORD not in stored
    assert verify_password(PASSWORD, stored) and not verify_password("wrong-pass-1", stored)


def test_session_cookie_flags_and_token_not_stored(app):
    c = Client(app)
    c.call("POST", "/api/auth/register", {"email": "a@example.com", "password": PASSWORD, "consent": True})
    st, body, headers = c.call("POST", "/api/auth/login", {"email": "a@example.com", "password": PASSWORD})
    cookie = headers["Set-Cookie"]
    assert st == 200 and "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Secure" in cookie
    token = c.cookie.split("=", 1)[1]
    stored = json.dumps([dict(r) for r in app.db.query("SELECT * FROM sessions")])
    assert token and token not in stored
    assert "password_hash" not in json.dumps(body)


def test_registration_requires_consent_and_strong_password(app):
    c = Client(app)
    st, _body, _ = c.call("POST", "/api/auth/register", {"email": "b@example.com", "password": PASSWORD})
    assert st == 400
    st, _body, _ = c.call("POST", "/api/auth/register", {"email": "b@example.com", "password": "short",
                                                         "consent": True})
    assert st == 400


def test_login_errors_do_not_enumerate_accounts(app):
    Client(app).signup("known@example.com")
    c = Client(app, ip="10.0.0.9")
    st1, b1, _ = c.call("POST", "/api/auth/login", {"email": "known@example.com", "password": "wrong-pass-1"})
    st2, b2, _ = c.call("POST", "/api/auth/login", {"email": "nobody@example.com", "password": "wrong-pass-1"})
    assert st1 == st2 == 401 and b1["message_ar"] == b2["message_ar"]
    # registering an existing address answers exactly like a new one
    r1 = c.call("POST", "/api/auth/register", {"email": "known@example.com", "password": PASSWORD, "consent": True})
    assert r1[0] == 201 and "dev_verification_token" not in r1[1]


def test_login_lockout_after_repeated_failures(app):
    Client(app).signup("lock@example.com")
    c = Client(app, ip="10.0.0.7")
    for _ in range(5):
        assert c.call("POST", "/api/auth/login", {"email": "lock@example.com", "password": "wrong-pass-1"})[0] == 401
    st, _, _ = c.call("POST", "/api/auth/login", {"email": "lock@example.com", "password": PASSWORD})
    assert st == 429


def test_csrf_and_cross_origin_are_refused(app):
    c = Client(app)
    c.signup("csrf@example.com")
    st, body, _ = c.call("POST", "/api/watchlists", {"name": "x"}, csrf=False)
    assert st == 403 and body["error"] == "csrf"
    st, body, _ = c.call("POST", "/api/watchlists", {"name": "x"}, headers={"Origin": "https://evil.example"})
    assert st == 403 and body["error"] == "cross_origin"
    st, _, _ = c.call("POST", "/api/watchlists", {"name": "x"}, headers={"Origin": "https://platform.test"})
    assert st == 201


def test_logout_revokes_session_and_password_change_revokes_others(app):
    a = Client(app)
    a.signup("s@example.com")
    b = Client(app)
    st, body, _ = b.call("POST", "/api/auth/login", {"email": "s@example.com", "password": PASSWORD})
    b.csrf = body["csrf_token"]
    st, _, _ = a.call("POST", "/api/account/password", {"current": PASSWORD, "new": "another-pass-77"})
    assert st == 200
    assert b.call("GET", "/api/me")[0] == 401      # other device signed out
    assert a.call("GET", "/api/me")[0] == 200      # this device kept
    a.call("POST", "/api/auth/logout", {})
    assert a.call("GET", "/api/me")[0] == 401


def test_email_verification_and_password_reset_tokens_are_single_use(app):
    c = Client(app)
    st, body, _ = c.call("POST", "/api/auth/register", {"email": "v@example.com", "password": PASSWORD,
                                                        "consent": True})
    assert st == 201
    token = body["dev_verification_token"]
    assert c.call("POST", "/api/auth/verify", {"token": token})[0] == 200
    assert c.call("POST", "/api/auth/verify", {"token": token})[0] == 400
    _st, body, _ = c.call("POST", "/api/auth/reset-request", {"email": "v@example.com"})
    reset = body["dev_reset_token"]
    _st2, body2, _ = c.call("POST", "/api/auth/reset-request", {"email": "ghost@example.com"})
    assert body["message_ar"] == body2["message_ar"] and "dev_reset_token" not in body2
    assert c.call("POST", "/api/auth/reset", {"token": reset, "password": "brand-new-pass-9"})[0] == 200
    assert c.call("POST", "/api/auth/reset", {"token": reset, "password": "brand-new-pass-9"})[0] == 400
    assert c.call("POST", "/api/auth/login", {"email": "v@example.com", "password": "brand-new-pass-9"})[0] == 200


# ---------------------------------------------------------------- isolation (IDOR)

def test_two_users_cannot_read_or_change_each_others_data(app):
    alice, bob = Client(app, "10.1.1.1"), Client(app, "10.1.1.2")
    alice.signup("alice@example.com")
    bob.signup("bob@example.com")
    st, wl, _ = alice.call("POST", "/api/watchlists", {"name": "قائمتي"})
    wid = wl["id"]
    alice.call("POST", f"/api/watchlists/{wid}/symbols", {"symbol": "NVDA"})
    st, ds, _ = alice.call("POST", "/api/datasets", {"symbol": "NVDA", "csv": daily_csv(80), "rights_attested": True})
    did = ds["id"]

    assert bob.call("GET", "/api/watchlists")[1]["watchlists"] == []
    for method, path, body in (("GET", f"/api/watchlists/{wid}", None),
                               ("PATCH", f"/api/watchlists/{wid}", {"name": "hijack"}),
                               ("POST", f"/api/watchlists/{wid}/symbols", {"symbol": "AAPL"}),
                               ("DELETE", f"/api/watchlists/{wid}/symbols/NVDA", None),
                               ("DELETE", f"/api/watchlists/{wid}", None),
                               ("GET", f"/api/datasets/{did}/analysis", None),
                               ("DELETE", f"/api/datasets/{did}", None),
                               ("GET", f"/api/research?watchlist={wid}", None)):
        st, body, _ = bob.call(method, path, body)
        assert st == 404, (method, path, st, body)
    st, body, _ = bob.call("POST", "/api/backtests", {"dataset_id": did, "strategy": "breakout"})
    assert st in (403, 404)  # free plan has no lab; with the lab it is still not found
    app_grant(app, "bob@example.com", "pro")
    st, body, _ = bob.call("POST", "/api/backtests", {"dataset_id": did, "strategy": "breakout"})
    assert st == 404
    assert bob.call("GET", "/api/datasets")[1]["datasets"] == []
    export = bob.call("GET", "/api/account/export")[1]
    assert "NVDA" not in json.dumps(export) and "alice" not in json.dumps(export)
    # Alice's data is intact
    st, wl_after, _ = alice.call("GET", f"/api/watchlists/{wid}")
    assert wl_after["name"] == "قائمتي" and [s["symbol"] for s in wl_after["symbols"]] == ["NVDA"]


def app_grant(app: App, email: str, plan: str) -> None:
    uid = app.db.one("SELECT id FROM users WHERE email=?", (email,))["id"]
    from ghazi_platform import billing
    billing.admin_grant(app.db, actor_id=uid, user_id=uid, plan=plan, days=30)


def test_admin_surface_is_hidden_from_users_and_open_to_owner(app):
    user = Client(app)
    user.signup("user@example.com")
    assert user.call("GET", "/api/admin/overview")[0] == 404
    assert user.call("POST", "/api/admin/grant", {"user_id": 1, "plan": "pro", "days": 30})[0] == 404
    owner = Client(app)
    owner.signup("owner@example.com")
    st, body, _ = owner.call("GET", "/api/admin/overview")
    assert st == 200 and any(u["email"] == "user@example.com" for u in body["users"])
    uid = next(u["id"] for u in body["users"] if u["email"] == "user@example.com")
    st, body, _ = owner.call("POST", "/api/admin/grant", {"user_id": uid, "plan": "plus", "days": 14})
    assert st == 200
    assert user.call("GET", "/api/me")[1]["user"]["plan"]["code"] == "plus"


# ---------------------------------------------------------------- entitlements

def test_free_plan_limits_are_enforced_on_the_server(app):
    c = Client(app)
    c.signup("free@example.com")
    assert c.call("POST", "/api/watchlists", {"name": "one"})[0] == 201
    st, body, _ = c.call("POST", "/api/watchlists", {"name": "two"})
    assert st == 403 and body["limit"] == "max_watchlists"
    wid = c.call("GET", "/api/watchlists")[1]["watchlists"][0]["id"]
    for i in range(10):
        assert c.call("POST", f"/api/watchlists/{wid}/symbols", {"symbol": f"T{i}"})[0] == 200
    st, body, _ = c.call("POST", f"/api/watchlists/{wid}/symbols", {"symbol": "OVER"})
    assert st == 403 and body["limit"] == "max_symbols_per_watchlist"
    st, ds, _ = c.call("POST", "/api/datasets", {"symbol": "ABC", "csv": daily_csv(80), "rights_attested": True})
    st, body, _ = c.call("POST", "/api/backtests", {"dataset_id": ds["id"], "strategy": "breakout"})
    assert st == 403 and body["feature"] == "backtest_lab"


def test_lapsed_subscription_falls_back_to_free(app):
    c = Client(app)
    c.signup("lapse@example.com")
    uid = app.db.one("SELECT id FROM users WHERE email='lapse@example.com'")["id"]
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    with app.db.tx() as conn:
        conn.execute("UPDATE subscriptions SET plan='pro', status='active', current_period_end=? WHERE user_id=?",
                     (past, uid))
    assert c.call("GET", "/api/me")[1]["user"]["plan"]["code"] == "free"


def test_symbol_validation_rejects_injection(app):
    c = Client(app)
    c.signup("sym@example.com")
    wid = c.call("POST", "/api/watchlists", {"name": "w"})[1]["id"]
    for bad in ("<script>", "AAPL;DROP", "", "toolongsymbol"):
        assert c.call("POST", f"/api/watchlists/{wid}/symbols", {"symbol": bad})[0] == 400


# ---------------------------------------------------------------- account data

def test_export_and_delete_account(app):
    c = Client(app)
    c.signup("gone@example.com")
    c.call("POST", "/api/watchlists", {"name": "w"})
    st, export, headers = c.call("GET", "/api/account/export")
    assert st == 200 and export["profile"]["email"] == "gone@example.com"
    assert "attachment" in headers["Content-Disposition"] and "password" not in json.dumps(export)
    assert c.call("POST", "/api/account/delete", {"password": "wrong-pass-1"})[0] == 403
    assert c.call("POST", "/api/account/delete", {"password": PASSWORD})[0] == 200
    assert app.db.one("SELECT COUNT(*) AS n FROM users")["n"] == 0
    assert app.db.one("SELECT COUNT(*) AS n FROM watchlists")["n"] == 0
    assert app.db.one("SELECT COUNT(*) AS n FROM sessions")["n"] == 0
    leftover = json.dumps([dict(r) for r in app.db.query("SELECT * FROM audit_events")])
    assert "gone@example.com" not in leftover


# ---------------------------------------------------------------- data rights

def test_rights_gate_fails_closed_for_unknown_and_restricted():
    path = ROOT / "data" / "source_rights.json"
    assert rights.commercial_display("openfda", derived=False, rights_path=path)["allowed"] is True
    assert rights.commercial_display("yahoo", derived=False, rights_path=path)["allowed"] is False
    assert rights.commercial_display("alpaca", derived=True, rights_path=path)["allowed"] is False
    assert rights.commercial_display("sec_edgar", derived=False, rights_path=path)["allowed"] is False  # UNKNOWN
    assert rights.commercial_display(None, derived=False, rights_path=path)["allowed"] is False
    assert rights.provider_for("ClinicalTrials.gov") is None


def _write_artifacts(dirpath: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    brief = {"generated_at": now, "stocks": [{"symbol": "AVGO", "observed_price": 328.75, "target_1": 311.39}],
             "catalysts": [
                 {"symbol": "LLY", "headline": "Registry results posted", "source": "ClinicalTrials.gov",
                  "source_url": "https://clinicaltrials.gov/study/NCT1", "published_at": "2026-10-16"},
                 {"symbol": "MRK", "headline": "FDA approval letter", "source": "openFDA",
                  "source_url": "https://api.fda.gov/drug/x", "published_at": "2026-10-17"},
                 {"symbol": "AAPL", "headline": "Yahoo story", "source": "Yahoo Finance",
                  "source_url": "https://finance.yahoo.com/x", "published_at": "2026-10-18"},
                 {"symbol": "TSLA", "headline": "no link", "source": "openFDA", "published_at": "2026-10-18"}]}
    (dirpath / "decision_brief.json").write_text(json.dumps(brief))
    (dirpath / "latest.json").write_text(json.dumps({"generated_at": now, "stocks": [{"symbol": "X", "price": 5,
                                                                                    "source": "yfinance"}]}))
    (dirpath / "health.json").write_text(json.dumps({"status": "degraded", "generated_at": now}))
    (dirpath / "index_radar.json").write_text(json.dumps({"status": "SOURCE_TERMS_BLOCKED", "reason_ar": "محجوب",
                                                          "generated_at": "2026-10-20T18:41:17+00:00"}))


def test_research_center_withholds_uncleared_text_and_drops_unverifiable(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write_artifacts(data)
    cfg = Config(enabled=True, db_path=str(tmp_path / "r.sqlite3"), public_data_dir=data)
    app = App(cfg)
    st, body, _ = Client(app).call("GET", "/api/research")
    assert st == 200
    by_symbol = {i["symbol"]: i for i in body["items"]}
    assert by_symbol["MRK"]["mode"] == "FULL" and by_symbol["MRK"]["title"] == "FDA approval letter"
    assert by_symbol["LLY"]["mode"] == "LINK_ONLY" and by_symbol["LLY"]["title"] is None
    assert "TSLA" not in by_symbol and body["dropped_unverifiable"] == 1
    # the Yahoo item is removed by the publication guard before the rights gate
    assert "AAPL" not in by_symbol
    assert "Registry results posted" not in json.dumps(body)


def test_dashboard_never_shows_prices_of_unknown_provenance(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write_artifacts(data)
    app = App(Config(enabled=True, db_path=str(tmp_path / "d.sqlite3"), public_data_dir=data))
    st, body, _ = Client(app).call("GET", "/api/dashboard")
    text = json.dumps(body)
    assert st == 200 and "328.75" not in text and "311.39" not in text
    prices = next(s for s in body["sections"] if s["key"] == "prices")
    assert prices["state"] == "NOT_AVAILABLE"
    index = next(s for s in body["sections"] if s["key"] == "index")
    assert index["state"] == "NOT_AVAILABLE" and index["freshness"]["state"] == "STALE"
    assert body["authority"]["probability"] is None and body["authority"]["execution"] is False


def test_dashboard_reads_real_repository_artifacts(app):
    st, body, _ = Client(app).call("GET", "/api/dashboard")
    assert st == 200 and {s["key"] for s in body["sections"]} >= {"index", "spx", "prices"}
    st, body, _ = Client(app).call("GET", "/api/research")
    assert st == 200 and all(i["url"].startswith("https://") for i in body["items"])


# ---------------------------------------------------------------- analysis and backtest

def test_dataset_upload_rejects_inconsistent_bars_and_requires_attestation(app):
    c = Client(app)
    c.signup("data@example.com")
    good = daily_csv(30)
    assert c.call("POST", "/api/datasets", {"symbol": "ABC", "csv": good})[0] == 400
    bad = "date,open,high,low,close\n2025-01-06,10,9,8,9.5\n2025-01-07,10,11,9,10"
    st, body, _ = c.call("POST", "/api/datasets", {"symbol": "ABC", "csv": bad, "rights_attested": True})
    assert st == 400 and "سطر 2" in body["message_ar"]


def test_analysis_uses_existing_engine_and_has_no_probability(app):
    c = Client(app)
    c.signup("an@example.com")
    did = c.call("POST", "/api/datasets", {"symbol": "NVDA", "csv": daily_csv(120), "rights_attested": True})[1]["id"]
    st, body, _ = c.call("GET", f"/api/datasets/{did}/analysis")
    assert st == 200 and body["card"]["available"] is True
    assert body["probability"] is None and body["execution_authority"] is False
    assert body["text_numbers_supported"] is True
    assert body["card"]["interpretation"]["frames"]["daily"]["trend"] in ("UP", "DOWN", "MIXED")
    assert any(m["item"] == "options" for m in body["card"]["missing"])


def _bars(rows):
    out = []
    d = date(2025, 1, 6)
    for o, h, lo, c in rows:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"date": d.isoformat(), "open": o, "high": h, "low": lo, "close": c, "volume": 1})
        d += timedelta(days=1)
    return out


def test_same_bar_stop_and_target_is_ambiguous_not_a_win():
    flat = [(100, 101, 99, 100)] * 20
    rows = flat + [(100, 103, 99.5, 102.5),        # breakout signal at close
                   (102.5, 130, 70, 100)]          # entry bar touches both stop and target
    p = backtest.validate("breakout", {"lookback": 20, "stop_atr": 1, "target_atr": 1, "max_hold": 5})
    trades = backtest.simulate("breakout", _bars(rows), p)
    assert trades and trades[0]["outcome"] == "AMBIGUOUS" and "net_return_pct" not in trades[0]
    summary = backtest.summarize(trades)
    assert summary["net_positive"] == 0 and summary["ambiguous_same_bar"] == 1


def test_signals_have_no_look_ahead():
    bars = _bars([(100 + i * 0.1, 101 + i * 0.1, 99 + i * 0.1, 100 + i * 0.1) for i in range(120)])
    p = backtest.validate("ema_cross", {"fast": 5, "slow": 20})
    base = [t for t in backtest.signals("ema_cross", bars, p) if t < 80]
    changed = bars[:80] + [{**b, "close": b["close"] * 3, "high": b["high"] * 3} for b in bars[80:]]
    assert [t for t in backtest.signals("ema_cross", changed, p) if t < 80] == base
    trades = backtest.simulate("ema_cross", bars, p)
    for t in trades:
        assert t["entry_date"] > t["signal_date"]


def test_costs_reduce_returns_and_small_samples_show_no_rate():
    bars = [{"date": b["date"], **{k: b[k] for k in ("open", "high", "low", "close")}}
            for b in _csv_bars(daily_csv(260))]
    p0 = backtest.validate("breakout", {"commission_bps": 0, "slippage_bps": 0})
    p1 = backtest.validate("breakout", {"commission_bps": 10, "slippage_bps": 20})
    t0, t1 = backtest.simulate("breakout", bars, p0), backtest.simulate("breakout", bars, p1)
    r0 = [t["net_return_pct"] for t in t0 if "net_return_pct" in t]
    r1 = [t["net_return_pct"] for t in t1 if "net_return_pct" in t]
    assert r0 and all(b < a for a, b in zip(r0, r1))
    s = backtest.summarize(t1)
    if s["resolved"] < backtest.MIN_SAMPLE:
        assert s["net_positive_share"] is None and "insufficient_note_ar" in s


def _csv_bars(text):
    from ghazi_platform.workspace import parse_bars_csv
    return parse_bars_csv(text)


def test_backtest_lab_by_plan(app):
    c = Client(app)
    c.signup("lab@example.com")
    app_grant(app, "lab@example.com", "plus")
    did = c.call("POST", "/api/datasets", {"symbol": "SPY", "csv": daily_csv(260), "rights_attested": True})[1]["id"]
    st, body, _ = c.call("POST", "/api/backtests", {"dataset_id": did, "strategy": "breakout",
                                                    "params": {"oos_fraction": 0.3}})
    assert st == 403 and body["feature"] == "backtest_oos_split"   # OOS split is a pro feature
    st, body, _ = c.call("POST", "/api/backtests", {"dataset_id": did, "strategy": "ema_cross"})
    assert st == 201 and body["probability"] is None and "cost_sensitivity" not in body
    app_grant(app, "lab@example.com", "pro")
    st, body, _ = c.call("POST", "/api/backtests", {"dataset_id": did, "strategy": "breakout",
                                                    "params": {"oos_fraction": 0.3}})
    assert st == 201 and "split" in body and len(body["cost_sensitivity"]) == 4
    assert c.call("GET", f"/api/backtests/{body['id']}")[0] == 200
    st, body, _ = c.call("POST", "/api/backtests", {"dataset_id": did, "strategy": "ema_cross",
                                                    "params": {"fast": 50, "slow": 20}})
    assert st == 400


# ---------------------------------------------------------------- billing

def _event(**kw):
    base = {"id": "evt_1", "type": "subscription.activated", "user_id": 1, "plan": "pro", "period_days": 30,
            "created_at": datetime.now(timezone.utc).isoformat()}
    base.update(kw)
    return json.dumps(base).encode()


def test_webhook_requires_signature_and_is_idempotent(app):
    c = Client(app)
    c.signup("pay@example.com")
    uid = app.db.one("SELECT id FROM users WHERE email='pay@example.com'")["id"]
    body = _event(user_id=uid)
    hook = Client(app)
    assert hook.call("POST", "/api/billing/webhook", raw=body, headers={"X-Ghazi-Signature": "bad"})[0] == 401
    sig = sign("whsec_test", body)
    st, out, _ = hook.call("POST", "/api/billing/webhook", raw=body, headers={"X-Ghazi-Signature": sig})
    assert st == 200 and out["outcome"] == "applied"
    st, out, _ = hook.call("POST", "/api/billing/webhook", raw=body, headers={"X-Ghazi-Signature": sig})
    assert st == 200 and out["duplicate"] is True
    assert app.db.one("SELECT COUNT(*) AS n FROM billing_events")["n"] == 1
    assert c.call("GET", "/api/me")[1]["user"]["plan"]["code"] == "pro"
    # payment failure -> grace keeps the plan; refund -> free
    for i, kind in enumerate(("payment.failed", "payment.refunded"), start=2):
        b = _event(id=f"evt_{i}", type=kind, user_id=uid)
        hook.call("POST", "/api/billing/webhook", raw=b, headers={"X-Ghazi-Signature": sign("whsec_test", b)})
        expected = "pro" if kind == "payment.failed" else "free"
        assert c.call("GET", "/api/me")[1]["user"]["plan"]["code"] == expected


def test_webhook_rejects_stale_events_and_is_off_when_billing_disabled(app, tmp_path):
    old = _event(id="evt_old", created_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    st, body, _ = Client(app).call("POST", "/api/billing/webhook", raw=old,
                                   headers={"X-Ghazi-Signature": sign("whsec_test", old)})
    assert st == 400 and body["error"] == "stale_event"
    off = App(Config(enabled=True, db_path=str(tmp_path / "off.sqlite3"), billing_mode="disabled"))
    b = _event()
    assert Client(off).call("POST", "/api/billing/webhook", raw=b,
                            headers={"X-Ghazi-Signature": sign("", b)})[0] == 404


def test_live_billing_mode_is_refused():
    assert Config.from_env(billing_mode="live").billing_mode == "disabled"


def test_platform_does_not_write_public_or_state_files(app):
    before = {p: p.stat().st_mtime for p in (ROOT / "public" / "data").glob("*.json")}
    c = Client(app)
    c.signup("ro@example.com")
    c.call("GET", "/api/dashboard")
    c.call("GET", "/api/research")
    after = {p: p.stat().st_mtime for p in (ROOT / "public" / "data").glob("*.json")}
    assert before == after


def test_database_enforces_foreign_keys(tmp_path):
    db = Database(str(tmp_path / "fk.sqlite3"))
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError), db.tx() as conn:
        conn.execute("INSERT INTO watchlists(user_id, name, created_at, updated_at) VALUES (999,'x','t','t')")
