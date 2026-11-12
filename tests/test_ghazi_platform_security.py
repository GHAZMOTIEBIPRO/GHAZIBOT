"""Security regression tests for the platform alpha: privilege escalation, account
paths, rate limits, concurrency against plan limits, dev-mode refusal, log hygiene."""
from __future__ import annotations

import io
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

import pytest

from ghazi_platform import accounts
from ghazi_platform.__main__ import main as cli_main
from ghazi_platform.accounts import AccountError, grant_owner, revoke_owner
from ghazi_platform.config import Config, ConfigError
from ghazi_platform.web import App
from tests.test_ghazi_platform import (
    PASSWORD,
    Client,
    app_grant,
    daily_csv,
    make_config,
    make_owner,
)


@pytest.fixture
def app(tmp_path):
    return App(make_config(tmp_path))


def _uid(app, email):
    return app.db.one("SELECT id FROM users WHERE email=?", (email,))["id"]


# ------------------------------------------------------------ privilege escalation

def test_public_registration_never_creates_an_admin(app, monkeypatch):
    monkeypatch.setenv("GHAZI_PLATFORM_ADMIN_EMAILS", "owner@example.com")  # the removed mechanism
    c = Client(app)
    st, _, _ = c.call("POST", "/api/auth/register", {"email": "owner@example.com", "password": PASSWORD,
                                                      "consent": True, "role": "admin", "is_admin": True})
    assert st == 201
    c.login("owner@example.com")
    assert app.db.one("SELECT role FROM users WHERE email='owner@example.com'")["role"] == "user"
    assert c.call("GET", "/api/me")[1]["user"]["role"] == "user"
    assert c.call("GET", "/api/admin/overview")[0] == 404


def test_email_verification_does_not_grant_admin(app):
    c = Client(app)
    c.signup("owner@example.com", verify=True)
    assert c.call("GET", "/api/me")[1]["user"]["email_verified"] is True
    assert c.call("GET", "/api/admin/overview")[0] == 404


def test_grant_owner_requires_existing_verified_account(app):
    with pytest.raises(AccountError) as missing:
        grant_owner(app.db, email="nobody@example.com", via="test")
    assert missing.value.status == 404
    Client(app).signup("squat@example.com", verify=False)
    with pytest.raises(AccountError) as unverified:
        grant_owner(app.db, email="squat@example.com", via="test")
    assert unverified.value.status == 409
    assert app.db.one("SELECT role FROM users WHERE email='squat@example.com'")["role"] == "user"


def test_grant_signs_out_existing_sessions_and_is_audited(app):
    c = Client(app)
    c.signup("owner@example.com")
    stale = c.cookie
    grant_owner(app.db, email="owner@example.com", via="test")
    c.cookie = stale
    assert c.call("GET", "/api/me")[0] == 401          # role change forces a fresh login
    c.cookie, c.csrf = "", None
    c.login("owner@example.com")
    assert c.call("GET", "/api/admin/overview")[0] == 200
    actions = [r["action"] for r in app.db.query("SELECT action FROM audit_events")]
    assert "admin.role_granted" in actions


def test_admin_role_without_verified_email_or_grant_record_has_no_authority(app):
    c = Client(app)
    c.signup("half@example.com", verify=False)
    with app.db.tx() as conn:   # e.g. a hand-edited row or a future bug: role alone is not enough
        conn.execute("UPDATE users SET role='admin' WHERE email='half@example.com'")
    assert c.call("GET", "/api/admin/overview")[0] == 404
    assert c.call("GET", "/api/me")[1]["user"]["role"] == "user"
    assert c.call("GET", "/api/me")[1]["user"]["plan"]["code"] == "free"
    with app.db.tx() as conn:   # verified but no recorded grant: still nothing
        conn.execute("UPDATE users SET email_verified_at='2026-11-12T00:00:00+00:00' WHERE email='half@example.com'")
    assert c.call("GET", "/api/admin/overview")[0] == 404


def test_pre_registered_owner_address_is_recovered_by_reset_and_squatter_is_locked_out(app):
    attacker = Client(app, ip="10.9.9.9")
    attacker.signup("owner@example.com", password="attacker-pass-1", verify=False)
    with pytest.raises(AccountError):
        grant_owner(app.db, email="owner@example.com", via="test")
    # the real owner proves the mailbox through a reset
    owner = Client(app, ip="10.1.1.1")
    reset = owner.call("POST", "/api/auth/reset-request", {"email": "owner@example.com"})[1]["dev_reset_token"]
    assert owner.call("POST", "/api/auth/reset", {"token": reset, "password": "owner-pass-77"})[0] == 200
    assert attacker.call("GET", "/api/me")[0] == 401
    assert attacker.call("POST", "/api/auth/login", {"email": "owner@example.com",
                                                     "password": "attacker-pass-1"})[0] == 401
    assert app.db.one("SELECT role FROM users WHERE email='owner@example.com'")["role"] == "user"
    grant_owner(app.db, email="owner@example.com", via="test")
    owner.login("owner@example.com", "owner-pass-77")
    assert owner.call("GET", "/api/admin/overview")[0] == 200


def test_admin_api_cannot_create_admins_or_grant_to_unverified(app):
    owner = make_owner(app, Client(app))
    other = Client(app)
    other.signup("other@example.com", verify=False)
    uid = _uid(app, "other@example.com")
    for plan in ("admin", "owner", "pro'; --"):
        assert owner.call("POST", "/api/admin/grant", {"user_id": uid, "plan": plan, "days": 30})[0] == 400
    st, _body, _ = owner.call("POST", "/api/admin/grant", {"user_id": uid, "plan": "pro", "days": 30})
    assert st == 409                                    # unverified target
    assert app.db.one("SELECT role FROM users WHERE id=?", (uid,))["role"] == "user"


def test_revoke_owner_removes_authority_immediately(app):
    owner = make_owner(app, Client(app))
    revoke_owner(app.db, email="owner@example.com", via="test")
    assert owner.call("GET", "/api/admin/overview")[0] == 401   # sessions revoked
    owner.login("owner@example.com")
    assert owner.call("GET", "/api/admin/overview")[0] == 404


def test_cli_grant_owner(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "cli.sqlite3")
    app = App(make_config(tmp_path, db_path=db_path))
    Client(app).signup("owner@example.com")
    monkeypatch.setenv("GHAZI_PLATFORM_DB", db_path)
    monkeypatch.delenv("GHAZI_PLATFORM_DEV", raising=False)
    assert cli_main(["grant-owner", "--email", "nobody@example.com"]) == 1
    assert cli_main(["grant-owner", "--email", "owner@example.com"]) == 0
    assert "admin" in capsys.readouterr().out
    assert app.db.one("SELECT admin_granted_via FROM users WHERE email='owner@example.com'")[0] == "cli"


def test_no_http_route_writes_the_role():
    import inspect

    from ghazi_platform import web
    source = inspect.getsource(web)
    assert "grant_owner" not in source and "revoke_owner" not in source
    assert "role=" not in source.replace("effective_role", "")


# ------------------------------------------------------------ dev mode / config

def test_dev_mode_and_insecure_cookies_refused_outside_development(tmp_path, monkeypatch):
    with pytest.raises(ConfigError):
        App(Config(enabled=True, db_path=str(tmp_path / "a.sqlite3"), dev_mode=True))
    with pytest.raises(ConfigError):
        App(Config(enabled=True, db_path=str(tmp_path / "b.sqlite3"), secure_cookies=False))
    monkeypatch.delenv("GHAZI_PLATFORM_ENV", raising=False)
    monkeypatch.setenv("GHAZI_PLATFORM_DEV", "1")
    with pytest.raises(ConfigError):
        Config.from_env()                    # environment defaults to production
    monkeypatch.setenv("GHAZI_PLATFORM_ENV", "staging")
    with pytest.raises(ConfigError):
        Config.from_env()
    monkeypatch.setenv("GHAZI_PLATFORM_ENV", "development")
    assert Config.from_env().dev_mode is True


def test_production_never_returns_one_time_tokens(tmp_path):
    app = App(Config(enabled=True, db_path=str(tmp_path / "prod.sqlite3")))
    c = Client(app)
    st, body, _ = c.call("POST", "/api/auth/register", {"email": "p@example.com", "password": PASSWORD,
                                                        "consent": True})
    assert st == 201 and not any(k.startswith("dev_") for k in body)
    body = c.call("POST", "/api/auth/reset-request", {"email": "p@example.com"})[1]
    assert not any(k.startswith("dev_") for k in body)


def test_sandbox_billing_requires_a_real_secret(tmp_path):
    with pytest.raises(ConfigError):
        App(Config(enabled=True, db_path=str(tmp_path / "s.sqlite3"), billing_mode="sandbox",
                   billing_webhook_secret="short"))


# ------------------------------------------------------------ rate limits

@pytest.fixture
def strict_app(tmp_path):
    return App(make_config(tmp_path, register_per_ip=(5, 3600), token_attempts_per_ip=(20, 900)))


def test_registration_is_rate_limited_per_ip(strict_app):
    c = Client(strict_app, ip="10.5.5.5")
    codes = [c.call("POST", "/api/auth/register", {"email": f"r{i}@example.com", "password": PASSWORD,
                                                   "consent": True})[0] for i in range(7)]
    assert codes[:5] == [201] * 5 and codes[5:] == [429, 429]
    assert strict_app.db.one("SELECT COUNT(*) AS n FROM users")["n"] == 5
    assert Client(strict_app, ip="10.5.5.6").call("POST", "/api/auth/register", {
        "email": "other@example.com", "password": PASSWORD, "consent": True})[0] == 201


def test_reset_requests_are_limited_without_revealing_accounts(strict_app):
    Client(strict_app, ip="10.6.0.1").signup("known@example.com")
    c = Client(strict_app, ip="10.6.0.2")
    tokens = [c.call("POST", "/api/auth/reset-request", {"email": "known@example.com"})[1] for _ in range(5)]
    issued = [t for t in tokens if "dev_reset_token" in t]
    assert len(issued) == 3                               # per-address limit, silent
    assert {t["message_ar"] for t in tokens} == {tokens[0]["message_ar"]}
    codes = [c.call("POST", "/api/auth/reset-request", {"email": f"x{i}@example.com"})[0] for i in range(6)]
    assert codes[-1] == 429                               # per-IP limit (10/hour)


def test_token_guessing_is_rate_limited(strict_app):
    c = Client(strict_app, ip="10.7.0.1")
    codes = [c.call("POST", "/api/auth/verify", {"token": f"guess-{i}"})[0] for i in range(22)]
    assert codes[:20] == [400] * 20 and codes[20:] == [429, 429]


def test_login_failure_keys_do_not_store_email_addresses(app):
    c = Client(app)
    c.call("POST", "/api/auth/login", {"email": "secret.person@example.com", "password": "wrong-pass-1"})
    keys = json.dumps([dict(r) for r in app.db.query("SELECT key FROM rate_events")])
    assert "secret.person" not in keys


# ------------------------------------------------------------ sessions / CSRF / origin

def test_cross_site_fetch_metadata_and_null_origin_are_refused(app):
    c = Client(app)
    c.signup("o@example.com")
    assert c.call("POST", "/api/watchlists", {"name": "x"}, headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert c.call("POST", "/api/watchlists", {"name": "x"}, headers={"Origin": "null"})[0] == 403
    assert c.call("POST", "/api/watchlists", {"name": "x"}, headers={"Sec-Fetch-Site": "same-origin"})[0] == 201


def test_login_csrf_via_html_form_is_refused(app):
    Client(app).signup("f@example.com")
    c = Client(app)
    body = b"email=f%40example.com&password=correct-horse-42"
    env_headers = {"Origin": "https://evil.example"}
    st, _, _ = c.call("POST", "/api/auth/login", raw=body, headers=env_headers)
    assert st == 403
    # same-origin but a form body: refused because JSON is required
    c2 = Client(app)
    st, out, _ = c2.call("POST", "/api/auth/login", raw=body)
    assert st in (400, 415) or out.get("error") == "json_required"


def test_idle_session_expires(app):
    c = Client(app)
    c.signup("idle@example.com")
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(timespec="seconds")
    with app.db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at=?", (old,))
    assert c.call("GET", "/api/me")[0] == 401


def test_forged_or_oversized_session_cookie_is_ignored(app):
    c = Client(app)
    c.cookie = "__Host-ghazi_session=" + "A" * 5000
    assert c.call("GET", "/api/me")[0] == 401
    c.cookie = "ghazi_session=abc"  # the non-prefixed name is not accepted when cookies are secure
    assert c.call("GET", "/api/me")[0] == 401


# ------------------------------------------------------------ concurrency vs plan limits

def _parallel(fn, n):
    barrier = threading.Barrier(n)
    results = [None] * n

    def run(i):
        barrier.wait()
        results[i] = fn(i)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return results


def test_concurrent_requests_cannot_exceed_plan_limits(tmp_path):
    # Separate App instances on one file = separate processes (own connections, own locks).
    cfg = make_config(tmp_path, db_path=str(tmp_path / "race.sqlite3"))
    first = App(cfg)
    c = Client(first)
    c.signup("race@example.com")
    cookie, csrf = c.cookie, c.csrf
    apps = [App(cfg) for _ in range(8)]

    def client_for(i):
        k = Client(apps[i % len(apps)])
        k.cookie, k.csrf = cookie, csrf
        return k

    codes = _parallel(lambda i: client_for(i).call("POST", "/api/watchlists", {"name": f"w{i}"})[0], 12)
    assert codes.count(201) == 1 and all(x in (201, 403) for x in codes)   # free plan: 1 watchlist
    wid = c.call("GET", "/api/watchlists")[1]["watchlists"][0]["id"]
    codes = _parallel(lambda i: client_for(i).call("POST", f"/api/watchlists/{wid}/symbols",
                                                   {"symbol": f"S{i}"})[0], 24)
    assert codes.count(200) == 10                                           # 10 symbols per list
    n = first.db.one("SELECT COUNT(*) AS n FROM watchlist_symbols")["n"]
    assert n == 10


def test_concurrent_backtests_cannot_exceed_daily_quota(tmp_path):
    cfg = make_config(tmp_path, db_path=str(tmp_path / "bt.sqlite3"))
    first = App(cfg)
    c = Client(first)
    c.signup("bt@example.com")
    app_grant(first, "bt@example.com", "plus")        # 25 backtests / 24 h
    did = c.call("POST", "/api/datasets", {"symbol": "SPY", "csv": daily_csv(120), "rights_attested": True})[1]["id"]
    with first.db.tx() as conn:                        # 22 already used today
        for _ in range(22):
            conn.execute("INSERT INTO backtests(user_id, dataset_id, strategy, params_json, result_json, status,"
                         " created_at) VALUES (?,?,'breakout','{}','{}','done',?)",
                         (_uid(first, "bt@example.com"), did, datetime.now(timezone.utc).isoformat()))
    apps = [App(cfg) for _ in range(6)]

    def go(i):
        k = Client(apps[i % len(apps)])
        k.cookie, k.csrf = c.cookie, c.csrf
        return k.call("POST", "/api/backtests", {"dataset_id": did, "strategy": "breakout"})[0]

    codes = _parallel(go, 10)
    assert codes.count(201) == 3 and codes.count(403) == 7
    assert first.db.one("SELECT COUNT(*) AS n FROM backtests")["n"] == 25
    assert first.db.one("SELECT COUNT(*) AS n FROM backtests WHERE status='running'")["n"] == 0


def test_invalid_backtest_does_not_consume_quota(app):
    c = Client(app)
    c.signup("q@example.com")
    app_grant(app, "q@example.com", "plus")
    did = c.call("POST", "/api/datasets", {"symbol": "SPY", "csv": daily_csv(120), "rights_attested": True})[1]["id"]
    assert c.call("POST", "/api/backtests", {"dataset_id": did, "strategy": "nope"})[0] == 400
    assert app.db.one("SELECT COUNT(*) AS n FROM backtests")["n"] == 0


# ------------------------------------------------------------ logs and stored detail

def test_unhandled_error_returns_generic_500_and_logs_no_secrets(app, monkeypatch, caplog):
    secret = "tok_SUPERSECRET_123"

    def boom(*a, **k):
        raise RuntimeError(f"leaked {secret}")

    monkeypatch.setattr(accounts, "plans_catalog", boom)
    with caplog.at_level(logging.ERROR, logger="ghazi_platform"):
        st, body, _ = Client(app).call("GET", f"/api/plans?token={secret}")
    assert st == 500 and secret not in json.dumps(body)
    assert "RuntimeError" in caplog.text and secret not in caplog.text


def test_audit_and_rate_tables_hold_no_passwords_or_tokens(app):
    c = Client(app)
    reg = c.call("POST", "/api/auth/register", {"email": "audit@example.com", "password": PASSWORD,
                                                "consent": True})[1]
    c.call("POST", "/api/auth/verify", {"token": reg["dev_verification_token"]})
    c.login("audit@example.com")
    reset = c.call("POST", "/api/auth/reset-request", {"email": "audit@example.com"})[1]["dev_reset_token"]
    c.call("POST", "/api/auth/reset", {"token": reset, "password": "new-password-99"})
    session_token = c.cookie.split("=", 1)[1]
    dump = json.dumps([dict(r) for t in ("audit_events", "rate_events", "one_time_tokens", "sessions")
                       for r in app.db.query(f"SELECT * FROM {t}")])
    for value in (PASSWORD, "new-password-99", reg["dev_verification_token"], reset, session_token):
        assert value not in dump


def test_dev_server_log_line_drops_query_strings():
    from ghazi_platform.__main__ import _QuietHandler
    handler = _QuietHandler.__new__(_QuietHandler)
    handler.command, handler.path = "GET", "/api/research?watchlist=5&token=abc"
    err = io.StringIO()
    import sys
    old, sys.stderr = sys.stderr, err
    try:
        handler.log_message("%s %s %s", "x", "200", "-")
    finally:
        sys.stderr = old
    assert "token" not in err.getvalue() and "/api/research" in err.getvalue()
