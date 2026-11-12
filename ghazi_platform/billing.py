"""Subscription management without real money.

- `disabled` (default): no checkout, no webhooks; only an admin can grant a plan
  (for design-partner pilots), and every grant is audited.
- `sandbox`: a signed (HMAC-SHA256) and idempotent webhook endpoint that lets the
  team test the subscription state machine (activate, renew, grace, cancel,
  expire, refund) with fake events. No payment processor is called.

There is deliberately no live mode. Choosing a processor that supports Saudi
merchants, signing its contract and adding its adapter is an owner decision
(PR #424 §9) and a separate change.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from . import audit
from .accounts import AccountError
from .config import Config
from .db import Database
from .entitlements import PLANS
from .security import iso, parse_iso, signature_ok, utcnow

EVENT_KINDS = {"subscription.activated", "subscription.renewed", "payment.failed", "subscription.canceled",
               "subscription.expired", "payment.refunded"}
GRACE_DAYS = 3
MAX_EVENT_AGE_SECONDS = 300


def _set(conn, user_id: int, *, plan: str, status: str, source: str, period_end: str | None) -> None:
    conn.execute(
        "INSERT INTO subscriptions(user_id, plan, status, source, current_period_end, updated_at) VALUES (?,?,?,?,?,?)"
        " ON CONFLICT(user_id) DO UPDATE SET plan=excluded.plan, status=excluded.status, source=excluded.source,"
        " current_period_end=excluded.current_period_end, updated_at=excluded.updated_at",
        (user_id, plan, status, source, period_end, iso(utcnow())))


def admin_grant(db: Database, *, actor_id: int, user_id: Any, plan: Any, days: Any, ip: str = "") -> dict[str, Any]:
    if plan not in PLANS:
        raise AccountError("خطة غير معروفة.")
    try:
        uid, n_days = int(user_id), int(days)
    except (TypeError, ValueError):
        raise AccountError("قيم غير صالحة.") from None
    if not 1 <= n_days <= 366:
        raise AccountError("المدة بين 1 و366 يومًا.")
    if not db.one("SELECT 1 FROM users WHERE id=?", (uid,)):
        raise AccountError("المستخدم غير موجود.", 404)
    end = iso(utcnow() + timedelta(days=n_days)) if plan != "free" else None
    with db.tx() as conn:
        _set(conn, uid, plan=plan, status="active", source="admin_grant" if plan != "free" else "default",
             period_end=end)
    audit.record(db, "billing.admin_grant", user_id=uid, actor_id=actor_id, ip=ip, plan=plan, days=n_days)
    return {"user_id": uid, "plan": plan, "current_period_end": end}


def handle_webhook(db: Database, cfg: Config, body: bytes, signature: str) -> tuple[int, dict[str, Any]]:
    """Returns (http_status, response). Fails closed on every doubt."""
    if cfg.billing_mode != "sandbox":
        return 404, {"error": "billing_disabled"}
    if not signature_ok(cfg.billing_webhook_secret, body, signature):
        audit.record(db, "billing.webhook_rejected", reason="bad_signature")
        return 401, {"error": "bad_signature"}
    try:
        event = json.loads(body.decode("utf-8"))
        event_id = str(event["id"])
        kind = str(event["type"])
        user_id = int(event["user_id"])
        created = parse_iso(str(event["created_at"]))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return 400, {"error": "malformed_event"}
    if created.tzinfo is None:
        return 400, {"error": "naive_timestamp"}
    age = (utcnow() - created).total_seconds()
    if age > MAX_EVENT_AGE_SECONDS or age < -60:
        audit.record(db, "billing.webhook_rejected", reason="stale_or_future", event=event_id)
        return 400, {"error": "stale_event"}
    if kind not in EVENT_KINDS:
        return 400, {"error": "unknown_type"}
    plan = str(event.get("plan") or "")
    if kind in ("subscription.activated", "subscription.renewed") and plan not in ("plus", "pro"):
        return 400, {"error": "unknown_plan"}

    with db.tx() as conn:
        # Idempotency: the provider event id is unique; a replay changes nothing.
        if conn.execute("SELECT 1 FROM billing_events WHERE provider_event_id=?", (event_id,)).fetchone():
            return 200, {"ok": True, "duplicate": True}
        exists = conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone()
        outcome = "applied"
        if not exists:
            outcome = "unknown_user"
        else:
            current = conn.execute("SELECT plan FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
            current_plan = current["plan"] if current else "free"
            now = utcnow()
            if kind in ("subscription.activated", "subscription.renewed"):
                _set(conn, user_id, plan=plan, status="active", source="sandbox_billing",
                     period_end=iso(now + timedelta(days=int(event.get("period_days") or 30))))
            elif kind == "payment.failed":
                _set(conn, user_id, plan=current_plan, status="grace", source="sandbox_billing",
                     period_end=iso(now + timedelta(days=GRACE_DAYS)))
            elif kind in ("subscription.canceled", "subscription.expired", "payment.refunded"):
                _set(conn, user_id, plan="free", status="canceled" if kind != "subscription.expired" else "expired",
                     source="sandbox_billing", period_end=None)
        conn.execute("INSERT INTO billing_events(provider_event_id, user_id, kind, payload_json, received_at, outcome)"
                     " VALUES (?,?,?,?,?,?)",
                     (event_id, user_id if exists else None, kind,
                      json.dumps({k: event.get(k) for k in ("type", "plan", "period_days", "created_at")}),
                      iso(utcnow()), outcome))
    audit.record(db, "billing.webhook", user_id=user_id if exists else None, event=event_id, kind=kind,
                 outcome=outcome)
    return 200, {"ok": True, "outcome": outcome}


def admin_overview(db: Database) -> dict[str, Any]:
    users = [dict(r) for r in db.query(
        "SELECT u.id, u.email, u.role, u.created_at, u.email_verified_at, s.plan, s.status, s.source,"
        " s.current_period_end FROM users u LEFT JOIN subscriptions s ON s.user_id=u.id ORDER BY u.id LIMIT 500")]
    events = [dict(r) for r in db.query("SELECT provider_event_id, user_id, kind, outcome, received_at FROM billing_events"
                                        " ORDER BY id DESC LIMIT 50")]
    audits = [dict(r) for r in db.query("SELECT user_id, actor_id, action, detail_json, at FROM audit_events"
                                        " ORDER BY id DESC LIMIT 100")]
    counts: dict[str, int] = {}
    for u in users:
        counts[u.get("plan") or "free"] = counts.get(u.get("plan") or "free", 0) + 1
    return {"users": users, "plan_counts": counts, "billing_events": events, "audit_events": audits}
