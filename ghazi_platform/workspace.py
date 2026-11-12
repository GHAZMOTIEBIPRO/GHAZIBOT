"""Private workspace: watchlists and user-uploaded price datasets.

Every read and write filters on the owner's user_id inside the SQL statement; a
row owned by someone else is reported as "not found" (never "forbidden"), so ids
of other users' objects cannot be probed.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import date
from typing import Any

from . import audit
from .accounts import AccountError, SessionUser, subscription_of
from .db import Database
from .entitlements import effective_plan, require_below, require_feature
from .security import iso, utcnow

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
RIGHTS_ATTESTATION_AR = ("أقر بأن هذه البيانات ملكي أو أملك حق استخدامها لتحليلي الخاص، "
                         "وأنها لن تُعرض لغيري من خلال المنصة.")


def plan_for(db: Database, user: SessionUser):
    return effective_plan(subscription_of(db, user.id), user.role)


def clean_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not SYMBOL_RE.match(symbol):
        raise AccountError("رمز السهم غير صالح.")
    return symbol


def _clean_name(value: Any) -> str:
    name = str(value or "").strip()
    if not 1 <= len(name) <= 60:
        raise AccountError("اسم القائمة يجب أن يكون بين 1 و60 حرفًا.")
    return name


def _owned_watchlist(db: Database, user: SessionUser, watchlist_id: Any) -> dict[str, Any]:
    try:
        wid = int(watchlist_id)
    except (TypeError, ValueError):
        raise AccountError("القائمة غير موجودة.", 404) from None
    row = db.one("SELECT id, name, created_at, updated_at FROM watchlists WHERE id=? AND user_id=?", (wid, user.id))
    if not row:
        raise AccountError("القائمة غير موجودة.", 404)
    return dict(row)


def list_watchlists(db: Database, user: SessionUser) -> list[dict[str, Any]]:
    out = []
    for wl in db.query("SELECT id, name, created_at, updated_at FROM watchlists WHERE user_id=? ORDER BY id", (user.id,)):
        symbols = [dict(r) for r in db.query(
            "SELECT ws.symbol, ws.note, ws.added_at FROM watchlist_symbols ws JOIN watchlists w ON w.id=ws.watchlist_id"
            " WHERE ws.watchlist_id=? AND w.user_id=? ORDER BY ws.symbol", (wl["id"], user.id))]
        out.append({**dict(wl), "symbols": symbols})
    return out


def get_watchlist(db: Database, user: SessionUser, watchlist_id: Any) -> dict[str, Any]:
    wl = _owned_watchlist(db, user, watchlist_id)
    wl["symbols"] = [dict(r) for r in db.query(
        "SELECT symbol, note, added_at FROM watchlist_symbols WHERE watchlist_id=? ORDER BY symbol", (wl["id"],))]
    return wl


def create_watchlist(db: Database, user: SessionUser, name: Any, ip: str = "") -> dict[str, Any]:
    plan = plan_for(db, user)
    require_feature(plan, "watchlists")
    name_c = _clean_name(name)
    count = db.one("SELECT COUNT(*) AS n FROM watchlists WHERE user_id=?", (user.id,))["n"]
    require_below(count, plan.max_watchlists, "عدد قوائم المراقبة", "max_watchlists")
    now = iso(utcnow())
    with db.tx() as conn:
        if conn.execute("SELECT 1 FROM watchlists WHERE user_id=? AND name=?", (user.id, name_c)).fetchone():
            raise AccountError("لديك قائمة بهذا الاسم.", 409)
        cur = conn.execute("INSERT INTO watchlists(user_id, name, created_at, updated_at) VALUES (?,?,?,?)",
                           (user.id, name_c, now, now))
    audit.record(db, "watchlist.created", user_id=user.id, ip=ip, watchlist=cur.lastrowid)
    return get_watchlist(db, user, cur.lastrowid)


def rename_watchlist(db: Database, user: SessionUser, watchlist_id: Any, name: Any, ip: str = "") -> dict[str, Any]:
    wl = _owned_watchlist(db, user, watchlist_id)
    name_c = _clean_name(name)
    with db.tx() as conn:
        clash = conn.execute("SELECT 1 FROM watchlists WHERE user_id=? AND name=? AND id<>?",
                             (user.id, name_c, wl["id"])).fetchone()
        if clash:
            raise AccountError("لديك قائمة بهذا الاسم.", 409)
        conn.execute("UPDATE watchlists SET name=?, updated_at=? WHERE id=? AND user_id=?",
                     (name_c, iso(utcnow()), wl["id"], user.id))
    audit.record(db, "watchlist.renamed", user_id=user.id, ip=ip, watchlist=wl["id"])
    return get_watchlist(db, user, wl["id"])


def delete_watchlist(db: Database, user: SessionUser, watchlist_id: Any, ip: str = "") -> None:
    wl = _owned_watchlist(db, user, watchlist_id)
    with db.tx() as conn:
        conn.execute("DELETE FROM watchlists WHERE id=? AND user_id=?", (wl["id"], user.id))
    audit.record(db, "watchlist.deleted", user_id=user.id, ip=ip, watchlist=wl["id"])


def add_symbol(db: Database, user: SessionUser, watchlist_id: Any, symbol: Any, note: Any = "",
               ip: str = "") -> dict[str, Any]:
    wl = _owned_watchlist(db, user, watchlist_id)
    plan = plan_for(db, user)
    sym = clean_symbol(symbol)
    count = db.one("SELECT COUNT(*) AS n FROM watchlist_symbols WHERE watchlist_id=?", (wl["id"],))["n"]
    with db.tx() as conn:
        if conn.execute("SELECT 1 FROM watchlist_symbols WHERE watchlist_id=? AND symbol=?", (wl["id"], sym)).fetchone():
            raise AccountError("الرمز موجود في القائمة.", 409)
        require_below(count, plan.max_symbols_per_watchlist, "عدد الرموز في القائمة", "max_symbols_per_watchlist")
        conn.execute("INSERT INTO watchlist_symbols(watchlist_id, symbol, note, added_at) VALUES (?,?,?,?)",
                     (wl["id"], sym, str(note or "")[:200], iso(utcnow())))
        conn.execute("UPDATE watchlists SET updated_at=? WHERE id=?", (iso(utcnow()), wl["id"]))
    audit.record(db, "watchlist.symbol_added", user_id=user.id, ip=ip, watchlist=wl["id"], symbol=sym)
    return get_watchlist(db, user, wl["id"])


def remove_symbol(db: Database, user: SessionUser, watchlist_id: Any, symbol: Any, ip: str = "") -> dict[str, Any]:
    wl = _owned_watchlist(db, user, watchlist_id)
    sym = clean_symbol(symbol)
    with db.tx() as conn:
        cur = conn.execute("DELETE FROM watchlist_symbols WHERE watchlist_id=? AND symbol=?", (wl["id"], sym))
    if cur.rowcount == 0:
        raise AccountError("الرمز غير موجود في القائمة.", 404)
    audit.record(db, "watchlist.symbol_removed", user_id=user.id, ip=ip, watchlist=wl["id"], symbol=sym)
    return get_watchlist(db, user, wl["id"])


# ---------------------------------------------------------------- datasets

def parse_bars_csv(text: str) -> list[dict[str, Any]]:
    """Daily OHLCV CSV with a header: date, open, high, low, close[, volume].

    Rows that fail OHLC consistency are rejected with their line number rather
    than silently dropped, so the user sees what was wrong with the file.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise AccountError("الملف فارغ.")
    fields = {f.strip().lower(): f for f in reader.fieldnames if f}
    missing = [c for c in ("date", "open", "high", "low", "close") if c not in fields]
    if missing:
        raise AccountError("أعمدة ناقصة: " + ", ".join(missing))
    bars: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for lineno, row in enumerate(reader, start=2):
        try:
            d = date.fromisoformat(str(row[fields["date"]]).strip()[:10]).isoformat()
            o, h, lo, c = (float(row[fields[k]]) for k in ("open", "high", "low", "close"))
            v_raw = row.get(fields.get("volume", ""), "") if "volume" in fields else ""
            v = float(v_raw) if str(v_raw or "").strip() else None
        except (ValueError, TypeError, KeyError):
            problems.append(f"سطر {lineno}: قيمة غير صالحة")
            continue
        values = [o, h, lo, c] + ([v] if v is not None else [])
        if any(not math.isfinite(x) for x in values) or min(o, h, lo, c) <= 0:
            problems.append(f"سطر {lineno}: سعر غير موجب أو غير محدود")
            continue
        if not (lo <= min(o, c) and h >= max(o, c) and h >= lo):
            problems.append(f"سطر {lineno}: القمة/القاع لا يحتويان الافتتاح والإغلاق")
            continue
        if d in bars:
            problems.append(f"سطر {lineno}: تاريخ مكرر {d}")
            continue
        bars[d] = {"date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v}
        if len(bars) > 20000:
            raise AccountError("الملف أكبر من الحد (20000 شمعة).")
    if problems:
        raise AccountError("رُفض الملف: " + "؛ ".join(problems[:5]) + (" …" if len(problems) > 5 else ""))
    if len(bars) < 2:
        raise AccountError("يلزم شمعتان يوميتان على الأقل.")
    return [bars[k] for k in sorted(bars)]


def upload_dataset(db: Database, user: SessionUser, *, symbol: Any, label: Any, csv_text: Any,
                   rights_attested: Any, ip: str = "") -> dict[str, Any]:
    if rights_attested is not True:
        raise AccountError("يجب الإقرار بحق استخدام البيانات قبل الرفع.")
    plan = plan_for(db, user)
    require_feature(plan, "analysis")
    count = db.one("SELECT COUNT(*) AS n FROM datasets WHERE user_id=?", (user.id,))["n"]
    require_below(count, plan.max_datasets, "عدد ملفات البيانات", "max_datasets")
    sym = clean_symbol(symbol)
    bars = parse_bars_csv(str(csv_text or ""))
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO datasets(user_id, symbol, label, rights_attestation, bars_json, bar_count, first_date, last_date,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (user.id, sym, str(label or sym)[:80], RIGHTS_ATTESTATION_AR, json.dumps(bars), len(bars),
             bars[0]["date"], bars[-1]["date"], iso(utcnow())))
    audit.record(db, "dataset.uploaded", user_id=user.id, ip=ip, dataset=cur.lastrowid, symbol=sym, bars=len(bars))
    return dataset_meta(db, user, cur.lastrowid)


def list_datasets(db: Database, user: SessionUser) -> list[dict[str, Any]]:
    return [dict(r) for r in db.query("SELECT id, symbol, label, bar_count, first_date, last_date, created_at"
                                      " FROM datasets WHERE user_id=? ORDER BY id DESC", (user.id,))]


def dataset_meta(db: Database, user: SessionUser, dataset_id: Any) -> dict[str, Any]:
    row = db.one("SELECT id, symbol, label, bar_count, first_date, last_date, created_at FROM datasets"
                 " WHERE id=? AND user_id=?", (_int(dataset_id), user.id))
    if not row:
        raise AccountError("ملف البيانات غير موجود.", 404)
    return dict(row)


def dataset_bars(db: Database, user: SessionUser, dataset_id: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    row = db.one("SELECT id, symbol, label, bars_json, last_date FROM datasets WHERE id=? AND user_id=?",
                 (_int(dataset_id), user.id))
    if not row:
        raise AccountError("ملف البيانات غير موجود.", 404)
    return {"id": row["id"], "symbol": row["symbol"], "label": row["label"], "last_date": row["last_date"]}, \
        json.loads(row["bars_json"])


def delete_dataset(db: Database, user: SessionUser, dataset_id: Any, ip: str = "") -> None:
    with db.tx() as conn:
        cur = conn.execute("DELETE FROM datasets WHERE id=? AND user_id=?", (_int(dataset_id), user.id))
    if cur.rowcount == 0:
        raise AccountError("ملف البيانات غير موجود.", 404)
    audit.record(db, "dataset.deleted", user_id=user.id, ip=ip, dataset=_int(dataset_id))


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1
