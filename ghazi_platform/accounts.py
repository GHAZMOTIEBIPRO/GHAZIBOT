"""Accounts: registration, login, sessions, verification, reset, export, deletion.

Rules:
- one generic error for a wrong e-mail or a wrong password (anti-enumeration),
  with the same scrypt cost spent for unknown e-mails;
- failed logins are counted per e-mail and per IP and locked for a window;
- only SHA-256 hashes of session and one-time tokens are stored;
- a password change or reset revokes every other session.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
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
    session_id: int
    csrf_token: str

    def public(self, db: Database) -> dict[str, Any]:
        sub = subscription_of(db, self.id)
        plan = effective_plan(sub, self.role)
        return {"id": self.id, "email": self.email, "display_name": self.display_name, "role": self.role,
                "email_verified": self.email_verified, "plan": plan_public(plan), "subscription": sub}


def normalize_email(email: Any) -> str:
    value = str(email or "").strip().lower()
    if not EMAIL_RE.match(value):
        raise AccountError("صيغة البريد الإلكتروني غير صحيحة.")
    return value


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
    if consent is not True:
        raise AccountError("يجب الموافقة على إشعار الخصوصية وحدود الخدمة.")
    email_n = normalize_email(email)
    problem = password_problem(password)
    if problem:
        raise AccountError(problem)
    name = str(display_name or "").strip()[:60]
    role = "admin" if email_n in cfg.admin_emails else "user"
    now = iso(utcnow())
    pw_hash = hash_password(password)
    with db.tx() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE email=?", (email_n,)).fetchone()
        if exists:
            # Do not reveal that the address is registered; nothing is created.
            user_id = None
        else:
            cur = conn.execute(
                "INSERT INTO users(email, password_hash, display_name, role, consent_version, consent_at, created_at)"
                " VALUES (?,?,?,?,?,?,?)", (email_n, pw_hash, name, role, CONSENT_VERSION, now, now))
            user_id = cur.lastrowid
            conn.execute("INSERT INTO subscriptions(user_id, plan, status, source, updated_at) VALUES (?,?,?,?,?)",
                         (user_id, "free", "active", "default", now))
    result: dict[str, Any] = {"ok": True, "message_ar": "إن كان البريد جديدًا فقد أُنشئ الحساب؛ تحقق من بريدك لتأكيده."}
    if user_id is not None:
        audit.record(db, "account.registered", user_id=user_id, ip=ip, role=role)
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


def _consume(db: Database, token: Any, purpose: str) -> int:
    if not isinstance(token, str) or not token:
        raise AccountError("الرمز غير صالح أو منتهي.")
    now = iso(utcnow())
    with db.tx() as conn:
        row = conn.execute("SELECT id, user_id, expires_at, used_at FROM one_time_tokens WHERE token_hash=? AND purpose=?",
                           (token_hash(token), purpose)).fetchone()
        if not row or row["used_at"] or parse_iso(row["expires_at"]) < utcnow():
            raise AccountError("الرمز غير صالح أو منتهي.")
        conn.execute("UPDATE one_time_tokens SET used_at=? WHERE id=?", (now, row["id"]))
        return int(row["user_id"])


def verify_email(db: Database, token: Any, ip: str = "") -> None:
    user_id = _consume(db, token, "verify_email")
    with db.tx() as conn:
        conn.execute("UPDATE users SET email_verified_at=? WHERE id=?", (iso(utcnow()), user_id))
    audit.record(db, "account.email_verified", user_id=user_id, ip=ip)


def _throttle_keys(email: str, ip: str) -> list[str]:
    return [f"email:{email}", f"ip:{ip or 'unknown'}"]


def _locked(db: Database, cfg: Config, keys: list[str]) -> bool:
    since = time.time() - cfg.login_window_seconds
    for key in keys:
        limit = cfg.login_max_failures if key.startswith("email:") else cfg.login_max_failures * 6
        row = db.one("SELECT COUNT(*) AS n FROM login_failures WHERE key=? AND at_unix>=?", (key, since))
        if row and row["n"] >= limit:
            return True
    return False


def login(db: Database, cfg: Config, *, email: Any, password: Any, ip: str = "",
          user_agent: str = "") -> tuple[str, SessionUser]:
    try:
        email_n = normalize_email(email)
    except AccountError:
        raise AccountError(GENERIC_LOGIN_ERROR, 401) from None
    keys = _throttle_keys(email_n, ip)
    if _locked(db, cfg, keys):
        raise AccountError("محاولات كثيرة. انتظر قليلًا ثم حاول مجددًا.", 429)
    row = db.one("SELECT id, password_hash FROM users WHERE email=?", (email_n,))
    ok = False
    if row is None:
        dummy_verify(str(password or ""))
    else:
        ok = verify_password(str(password or ""), row["password_hash"])
    if not ok:
        with db.tx() as conn:
            for key in keys:
                conn.execute("INSERT INTO login_failures(key, at_unix) VALUES (?,?)", (key, time.time()))
        audit.record(db, "auth.login_failed", user_id=row["id"] if row else None, ip=ip)
        raise AccountError(GENERIC_LOGIN_ERROR, 401)
    with db.tx() as conn:
        conn.execute("DELETE FROM login_failures WHERE key=?", (keys[0],))
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


def user_for_token(db: Database, token: str | None) -> SessionUser | None:
    if not token:
        return None
    row = db.one("SELECT s.id AS sid, s.csrf_token, s.expires_at, s.revoked_at, u.id, u.email, u.display_name,"
                 " u.role, u.email_verified_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",
                 (token_hash(token),))
    if not row or row["revoked_at"] or parse_iso(row["expires_at"]) < utcnow():
        return None
    with db.tx() as conn:
        conn.execute("UPDATE sessions SET last_seen_at=? WHERE id=?", (iso(utcnow()), row["sid"]))
    return SessionUser(id=row["id"], email=row["email"], display_name=row["display_name"], role=row["role"],
                       email_verified=bool(row["email_verified_at"]), session_id=row["sid"],
                       csrf_token=row["csrf_token"])


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
    try:
        email_n = normalize_email(email)
    except AccountError:
        return result
    row = db.one("SELECT id FROM users WHERE email=?", (email_n,))
    if row:
        token = _one_time(db, int(row["id"]), "reset_password", hours=1)
        audit.record(db, "account.reset_requested", user_id=int(row["id"]), ip=ip)
        if cfg.dev_mode:
            result["dev_reset_token"] = token
    return result


def reset_password(db: Database, *, token: Any, new: Any, ip: str = "") -> None:
    problem = password_problem(new)
    if problem:
        raise AccountError(problem)
    user_id = _consume(db, token, "reset_password")
    now = iso(utcnow())
    with db.tx() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), user_id))
        conn.execute("UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, user_id))
    audit.record(db, "account.password_reset", user_id=user_id, ip=ip)


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
                                   " WHERE user_id=?", (uid,))]
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
