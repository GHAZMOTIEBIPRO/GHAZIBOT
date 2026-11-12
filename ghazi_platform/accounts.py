"""Accounts: registration, login, sessions, verification, reset, owner role, export, deletion.

Rules:
- registration over HTTP always creates a plain user; no request field and no
  e-mail address can produce the admin role;
- the admin role is granted only by `grant_owner`, which is reachable from the
  server-side command line (`python -m ghazi_platform grant-owner ...`), never from
  HTTP, and only to an account whose e-mail ownership is already proven;
- admin authority is effective only while role=admin AND the e-mail is verified
  AND the grant is recorded (`SessionUser.is_admin`); e-mail verification on its
  own never changes the role;
- one generic error for a wrong e-mail or a wrong password (anti-enumeration),
  with the same scrypt cost spent for unknown e-mails;
- failed logins, registrations, reset requests and token attempts are rate
  limited; e-mail-keyed limits store a hash of the address, not the address;
- only SHA-256 hashes of session and one-time tokens are stored;
- a password change or reset revokes every other session; a role change revokes
  every session of that account.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from . import audit
from .config import Config
from .db import Database
from .entitlements import PLANS, effective_plan, plan_public
from .security import (
    dummy_verify,
    hash_password,
    in_hours,
    iso,
    new_token,
    parse_iso,
    password_problem,
    token_hash,
    utcnow,
    verify_password,
)

CONSENT_VERSION = "2026-11-12.alpha"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")
GENERIC_LOGIN_ERROR = "البريد أو كلمة المرور غير صحيحة."
TOO_MANY_AR = "محاولات كثيرة. انتظر قليلًا ثم حاول مجددًا."


class AccountError(Exception):
    def __init__(self, message_ar: str, status: int = 400):
        super().__init__(message_ar)
        self.message_ar = message_ar
        self.status = status


@dataclass
class SessionUser:
    id: int
    email: str
    display_name: str
    role: str
    email_verified: bool
    admin_granted: bool
    session_id: int
    csrf_token: str

    @property
    def is_admin(self) -> bool:
        """Admin authority needs the role, a proven e-mail and a recorded server-side grant."""
        return self.role == "admin" and self.email_verified and self.admin_granted

    @property
    def effective_role(self) -> str:
        return "admin" if self.is_admin else "user"

    def public(self, db: Database) -> dict[str, Any]:
        sub = subscription_of(db, self.id)
        plan = effective_plan(sub, self.effective_role)
        return {"id": self.id, "email": self.email, "display_name": self.display_name, "role": self.effective_role,
                "email_verified": self.email_verified, "plan": plan_public(plan), "subscription": sub}


def normalize_email(email: Any) -> str:
    value = str(email or "").strip().lower()
    if not EMAIL_RE.match(value):
        raise AccountError("صيغة البريد الإلكتروني غير صحيحة.")
    return value


def _email_key(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------- rate limits

def _count(db: Database, key: str, window: int) -> int:
    row = db.one("SELECT COUNT(*) AS n FROM rate_events WHERE key=? AND at_unix>=?", (key, time.time() - window))
    return int(row["n"]) if row else 0


def consume_rate(db: Database, key: str, limit: tuple[int, int]) -> bool:
    """Atomically record one event for `key`; False if the limit was already reached."""
    max_events, window = limit
    now = time.time()
    with db.tx() as conn:
        conn.execute("DELETE FROM rate_events WHERE at_unix < ?", (now - 86400,))
        n = conn.execute("SELECT COUNT(*) FROM rate_events WHERE key=? AND at_unix>=?",
                         (key, now - window)).fetchone()[0]
        if n >= max_events:
            return False
        conn.execute("INSERT INTO rate_events(key, at_unix) VALUES (?,?)", (key, now))
    return True


def subscription_of(db: Database, user_id: int) -> dict[str, Any] | None:
    row = db.one("SELECT plan, status, source, current_period_end, updated_at FROM subscriptions WHERE user_id=?",
                 (user_id,))
    if not row:
        return None
    sub = dict(row)
    # An expired period with no renewal falls back to free (fail closed).
    end = sub.get("current_period_end")
    if sub["status"] in ("active", "grace") and end and parse_iso(end) < utcnow():
        sub["status"] = "expired"
    return sub


def register(db: Database, cfg: Config, *, email: Any, password: Any, display_name: Any = "",
             consent: Any = False, ip: str = "") -> dict[str, Any]:
    if not consume_rate(db, f"register:ip:{ip or 'unknown'}", cfg.register_per_ip):
        raise AccountError(TOO_MANY_AR, 429)
    if consent is not True:
        raise AccountError("يجب الموافقة على إشعار الخصوصية وحدود الخدمة.")
    email_n = normalize_email(email)
    problem = password_problem(password)
    if problem:
        raise AccountError(problem)
    name = str(display_name or "").strip()[:60]
    now = iso(utcnow())
    pw_hash = hash_password(password)
    with db.tx() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE email=?", (email_n,)).fetchone()
        if exists:
            # Do not reveal that the address is registered; nothing is created.
            user_id = None
        else:
            # The role column is never taken from the request: every HTTP sign-up is a user.
            cur = conn.execute(
                "INSERT INTO users(email, password_hash, display_name, role, consent_version, consent_at, created_at)"
                " VALUES (?,?,?,'user',?,?,?)", (email_n, pw_hash, name, CONSENT_VERSION, now, now))
            user_id = cur.lastrowid
            conn.execute("INSERT INTO subscriptions(user_id, plan, status, source, updated_at) VALUES (?,?,?,?,?)",
                         (user_id, "free", "active", "default", now))
    result: dict[str, Any] = {"ok": True, "message_ar": "إن كان البريد جديدًا فقد أُنشئ الحساب؛ تحقق من بريدك لتأكيده."}
    if user_id is not None:
        audit.record(db, "account.registered", user_id=user_id, ip=ip)
        token = _one_time(db, user_id, "verify_email", hours=48)
        if cfg.dev_mode:
            result["dev_verification_token"] = token
    return result


def _one_time(db: Database, user_id: int, purpose: str, *, hours: float) -> str:
    token = new_token()
    with db.tx() as conn:
        conn.execute("UPDATE one_time_tokens SET used_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL",
                     (iso(utcnow()), user_id, purpose))
        conn.execute("INSERT INTO one_time_tokens(user_id, purpose, token_hash, expires_at) VALUES (?,?,?,?)",
                     (user_id, purpose, token_hash(token), in_hours(hours)))
    return token


def _consume(db: Database, cfg: Config, token: Any, purpose: str, ip: str) -> int:
    if not consume_rate(db, f"token:ip:{ip or 'unknown'}", cfg.token_attempts_per_ip):
        raise AccountError(TOO_MANY_AR, 429)
    if not isinstance(token, str) or not token or len(token) > 200:
        raise AccountError("الرمز غير صالح أو منتهي.")
    now = iso(utcnow())
    with db.tx() as conn:
        row = conn.execute("SELECT id, user_id, expires_at, used_at FROM one_time_tokens WHERE token_hash=? AND purpose=?",
                           (token_hash(token), purpose)).fetchone()
        if not row or row["used_at"] or parse_iso(row["expires_at"]) < utcnow():
            raise AccountError("الرمز غير صالح أو منتهي.")
        conn.execute("UPDATE one_time_tokens SET used_at=? WHERE id=?", (now, row["id"]))
        return int(row["user_id"])


def verify_email(db: Database, cfg: Config, token: Any, ip: str = "") -> None:
    """Proves ownership of the address. It never changes the role."""
    user_id = _consume(db, cfg, token, "verify_email", ip)
    with db.tx() as conn:
        conn.execute("UPDATE users SET email_verified_at=COALESCE(email_verified_at, ?) WHERE id=?",
                     (iso(utcnow()), user_id))
    audit.record(db, "account.email_verified", user_id=user_id, ip=ip)


def login(db: Database, cfg: Config, *, email: Any, password: Any, ip: str = "",
          user_agent: str = "") -> tuple[str, SessionUser]:
    try:
        email_n = normalize_email(email)
    except AccountError:
        raise AccountError(GENERIC_LOGIN_ERROR, 401) from None
    email_key = f"login:email:{_email_key(email_n)}"
    ip_key = f"login:ip:{ip or 'unknown'}"
    window = cfg.login_window_seconds
    if (_count(db, email_key, window) >= cfg.login_max_failures
            or _count(db, ip_key, window) >= cfg.login_max_failures * 6):
        raise AccountError(TOO_MANY_AR, 429)
    row = db.one("SELECT id, password_hash FROM users WHERE email=?", (email_n,))
    ok = False
    if row is None:
        dummy_verify(str(password or ""))
    else:
        ok = verify_password(str(password or ""), row["password_hash"])
    if not ok:
        with db.tx() as conn:
            for key in (email_key, ip_key):
                conn.execute("INSERT INTO rate_events(key, at_unix) VALUES (?,?)", (key, time.time()))
        audit.record(db, "auth.login_failed", user_id=row["id"] if row else None, ip=ip)
        raise AccountError(GENERIC_LOGIN_ERROR, 401)
    with db.tx() as conn:
        conn.execute("DELETE FROM rate_events WHERE key=?", (email_key,))
    token = start_session(db, cfg, int(row["id"]), user_agent=user_agent)
    audit.record(db, "auth.login", user_id=int(row["id"]), ip=ip)
    user = user_for_token(db, token)
    assert user is not None
    return token, user


def start_session(db: Database, cfg: Config, user_id: int, *, user_agent: str = "") -> str:
    token = new_token()
    now = iso(utcnow())
    with db.tx() as conn:
        conn.execute("INSERT INTO sessions(user_id, token_hash, csrf_token, created_at, expires_at, last_seen_at, user_agent)"
                     " VALUES (?,?,?,?,?,?,?)",
                     (user_id, token_hash(token), new_token(), now, in_hours(cfg.session_hours), now, user_agent[:200]))
    return token


def user_for_token(db: Database, token: str | None, *, idle_hours: float = 24) -> SessionUser | None:
    if not token or len(token) > 200:
        return None
    row = db.one("SELECT s.id AS sid, s.csrf_token, s.expires_at, s.last_seen_at, s.revoked_at, u.id, u.email,"
                 " u.display_name, u.role, u.email_verified_at, u.admin_granted_at"
                 " FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?", (token_hash(token),))
    now = utcnow()
    if (not row or row["revoked_at"] or parse_iso(row["expires_at"]) < now
            or parse_iso(row["last_seen_at"]) < now - timedelta(hours=idle_hours)):
        return None
    with db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (iso(now), row["sid"]))
    return SessionUser(id=row["id"], email=row["email"], display_name=row["display_name"], role=row["role"],
                       email_verified=bool(row["email_verified_at"]), admin_granted=bool(row["admin_granted_at"]),
                       session_id=row["sid"], csrf_token=row["csrf_token"])


def logout(db: Database, user: SessionUser, *, everywhere: bool = False, ip: str = "") -> None:
    now = iso(utcnow())
    with db.tx() as conn:
        if everywhere:
            conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, user.id))
        else:
            conn.execute("UPDATE sessions SET revoked_at=? WHERE id=? AND user_id=?", (now, user.session_id, user.id))
    audit.record(db, "auth.logout_all" if everywhere else "auth.logout", user_id=user.id, ip=ip)


def list_sessions(db: Database, user: SessionUser) -> list[dict[str, Any]]:
    rows = db.query("SELECT id, created_at, last_seen_at, expires_at, user_agent FROM sessions"
                    " WHERE user_id=? AND revoked_at IS NULL ORDER BY last_seen_at DESC", (user.id,))
    return [{**dict(r), "current": r["id"] == user.session_id} for r in rows
            if parse_iso(r["expires_at"]) >= utcnow()]


def revoke_session(db: Database, user: SessionUser, session_id: Any, ip: str = "") -> None:
    with db.tx() as conn:
        cur = conn.execute("UPDATE sessions SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL",
                           (iso(utcnow()), int(session_id), user.id))
    if cur.rowcount == 0:
        raise AccountError("الجلسة غير موجودة.", 404)
    audit.record(db, "auth.session_revoked", user_id=user.id, ip=ip, session=int(session_id))


def change_password(db: Database, user: SessionUser, *, current: Any, new: Any, ip: str = "") -> None:
    row = db.one("SELECT password_hash FROM users WHERE id=?", (user.id,))
    if not row or not verify_password(str(current or ""), row["password_hash"]):
        raise AccountError("كلمة المرور الحالية غير صحيحة.", 403)
    problem = password_problem(new)
    if problem:
        raise AccountError(problem)
    now = iso(utcnow())
    with db.tx() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), user.id))
        conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND id<>? AND revoked_at IS NULL",
                     (now, user.id, user.session_id))
    audit.record(db, "account.password_changed", user_id=user.id, ip=ip)


def request_reset(db: Database, cfg: Config, *, email: Any, ip: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "message_ar": "إن كان البريد مسجلًا فسيصله رابط إعادة التعيين."}
    if not consume_rate(db, f"reset:ip:{ip or 'unknown'}", cfg.reset_per_ip):
        raise AccountError(TOO_MANY_AR, 429)
    try:
        email_n = normalize_email(email)
    except AccountError:
        return result
    # Per-address limit is silent: the answer is the same, so it reveals nothing.
    if not consume_rate(db, f"reset:email:{_email_key(email_n)}", cfg.reset_per_email):
        return result
    row = db.one("SELECT id FROM users WHERE email=?", (email_n,))
    if row:
        token = _one_time(db, int(row["id"]), "reset_password", hours=1)
        audit.record(db, "account.reset_requested", user_id=int(row["id"]), ip=ip)
        if cfg.dev_mode:
            result["dev_reset_token"] = token
    return result


def reset_password(db: Database, cfg: Config, *, token: Any, new: Any, ip: str = "") -> None:
    problem = password_problem(new)
    if problem:
        raise AccountError(problem)
    user_id = _consume(db, cfg, token, "reset_password", ip)
    now = iso(utcnow())
    with db.tx() as conn:
        # Completing a reset proves control of the mailbox, so it also verifies the
        # address (this lets the real owner take back an address someone pre-registered).
        # It does not touch the role.
        conn.execute("UPDATE users SET password_hash=?, email_verified_at=COALESCE(email_verified_at, ?) WHERE id=?",
                     (hash_password(new), now, user_id))
        conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, user_id))
    audit.record(db, "account.password_reset", user_id=user_id, ip=ip)


# ---------------------------------------------------------------- owner role (server side only)

def grant_owner(db: Database, *, email: str, via: str) -> dict[str, Any]:
    """Give the admin role to an existing account whose e-mail is verified.

    Called only from the server command line; whoever runs it controls the host,
    which is the trust root. Every session of the account is revoked so the new
    role starts from a fresh login.
    """
    email_n = normalize_email(email)
    now = iso(utcnow())
    with db.tx() as conn:
        row = conn.execute("SELECT id, email_verified_at FROM users WHERE email=?", (email_n,)).fetchone()
        if not row:
            raise AccountError("لا يوجد حساب بهذا البريد. سجّل أولًا من الموقع ثم أكّد البريد.", 404)
        if not row["email_verified_at"]:
            raise AccountError("البريد غير مؤكد. لا يُمنح دور الإدارة قبل إثبات ملكية البريد.", 409)
        conn.execute("UPDATE users SET role='admin', admin_granted_at=?, admin_granted_via=? WHERE id=?",
                     (now, via[:80], row["id"]))
        conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, row["id"]))
    audit.record(db, "admin.role_granted", user_id=int(row["id"]), actor_id=None, via=via[:80])
    return {"user_id": int(row["id"]), "email": email_n, "role": "admin", "granted_at": now}


def revoke_owner(db: Database, *, email: str, via: str) -> dict[str, Any]:
    email_n = normalize_email(email)
    now = iso(utcnow())
    with db.tx() as conn:
        row = conn.execute("SELECT id FROM users WHERE email=?", (email_n,)).fetchone()
        if not row:
            raise AccountError("لا يوجد حساب بهذا البريد.", 404)
        conn.execute("UPDATE users SET role='user', admin_granted_at=NULL, admin_granted_via=NULL WHERE id=?",
                     (row["id"],))
        conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, row["id"]))
    audit.record(db, "admin.role_revoked", user_id=int(row["id"]), actor_id=None, via=via[:80])
    return {"user_id": int(row["id"]), "email": email_n, "role": "user"}


def export_data(db: Database, user: SessionUser) -> dict[str, Any]:
    """Everything the platform stores about the user (no password hash or token hashes)."""
    uid = user.id
    profile = dict(db.one("SELECT email, display_name, role, email_verified_at, consent_version, consent_at, created_at"
                          " FROM users WHERE id=?", (uid,)) or {})
    watchlists = []
    for wl in db.query("SELECT id, name, created_at, updated_at FROM watchlists WHERE user_id=? ORDER BY id", (uid,)):
        symbols = [dict(r) for r in db.query("SELECT symbol, note, added_at FROM watchlist_symbols WHERE watchlist_id=?"
                                            " ORDER BY symbol", (wl["id"],))]
        watchlists.append({**dict(wl), "symbols": symbols})
    datasets = [dict(r) for r in db.query("SELECT id, symbol, label, rights_attestation, bar_count, first_date, last_date,"
                                         " created_at, bars_json FROM datasets WHERE user_id=?", (uid,))]
    for d in datasets:
        d["bars"] = json.loads(d.pop("bars_json"))
    backtests = [{**dict(r), "params": json.loads(r["params_json"]), "result": json.loads(r["result_json"])}
                 for r in db.query("SELECT id, dataset_id, strategy, params_json, result_json, created_at FROM backtests"
                                   " WHERE user_id=? AND status='done'", (uid,))]
    for b in backtests:
        b.pop("params_json")
        b.pop("result_json")
    audit_rows = [dict(r) for r in db.query("SELECT action, detail_json, at FROM audit_events WHERE user_id=?"
                                            " ORDER BY id", (uid,))]
    audit.record(db, "account.exported", user_id=uid)
    return {"schema": "ghazi.platform.user_export.v1", "exported_at": iso(utcnow()), "profile": profile,
            "subscription": subscription_of(db, uid), "watchlists": watchlists, "datasets": datasets,
            "backtests": backtests, "audit_events": audit_rows}


def delete_account(db: Database, user: SessionUser, *, password: Any, ip: str = "") -> None:
    row = db.one("SELECT password_hash FROM users WHERE id=?", (user.id,))
    if not row or not verify_password(str(password or ""), row["password_hash"]):
        raise AccountError("كلمة المرور غير صحيحة.", 403)
    with db.tx() as conn:
        # ON DELETE CASCADE removes sessions, tokens, watchlists, datasets, backtests, subscription.
        conn.execute("DELETE FROM users WHERE id=?", (user.id,))
        # Audit rows are kept without personal detail, detached from the deleted user.
        conn.execute("UPDATE audit_events SET user_id=NULL, actor_id=NULL, ip='' WHERE user_id=? OR actor_id=?",
                     (user.id, user.id))
    audit.record(db, "account.deleted", ip="")


def plans_catalog() -> list[dict[str, Any]]:
    return [plan_public(p) for p in PLANS.values()]
