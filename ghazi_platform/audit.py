"""Internal audit log. Details never hold passwords, tokens or uploaded bars."""
from __future__ import annotations

import json
from typing import Any

from .db import Database
from .security import iso, utcnow

_FORBIDDEN_KEYS = {"password", "token", "csrf", "secret", "bars", "authorization", "cookie"}


def _clean(detail: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in detail.items() if not any(f in k.lower() for f in _FORBIDDEN_KEYS)}


def record(db: Database, action: str, *, user_id: int | None = None, actor_id: int | None = None,
           ip: str = "", **detail: Any) -> None:
    with db.tx() as conn:
        conn.execute("INSERT INTO audit_events(user_id, actor_id, action, detail_json, ip, at) VALUES (?,?,?,?,?,?)",
                     (user_id, actor_id if actor_id is not None else user_id, action,
                      json.dumps(_clean(detail), ensure_ascii=False, default=str), ip[:64], iso(utcnow())))
