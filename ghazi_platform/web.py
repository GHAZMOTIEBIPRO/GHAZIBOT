"""WSGI application for the platform alpha.

Security posture:
- the whole app answers 404 unless the feature flag is on;
- session cookie: HttpOnly, SameSite=Lax, Secure (unless explicitly disabled
  for localhost), opaque random token, only its hash stored;
- every state-changing request needs a JSON body and, when signed in, the
  per-session CSRF token in X-CSRF-Token; a cross-site Origin is refused;
- strict Content-Security-Policy (self only), no framing, no-store on the API;
- authorization happens here on the server: login, role and plan checks run
  before each handler, and handlers filter every query by the owner's id.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
from collections.abc import Callable
from datetime import timedelta
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import accounts, analysis, audit, backtest, billing, research, workspace
from .accounts import AccountError, SessionUser
from .config import Config
from .db import Database
from .entitlements import EntitlementError, require_below, require_feature
from .security import iso, utcnow

LOG = logging.getLogger("ghazi_platform")


def cookie_name(cfg: Config) -> str:
    # The __Host- prefix makes the browser reject the cookie unless it is Secure,
    # host-only (no Domain) and Path=/, so a sibling subdomain cannot plant one.
    return "__Host-ghazi_session" if cfg.secure_cookies else "ghazi_session"
MAX_JSON_BYTES = 64_000
STATIC_FILES = {"app.css", "app.js"}
SECURITY_HEADERS = [
    ("Content-Security-Policy", ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self';"
                                 " connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
]


class HttpError(Exception):
    def __init__(self, status: int, code: str, message_ar: str, **extra: Any):
        super().__init__(code)
        self.status, self.code, self.message_ar, self.extra = status, code, message_ar, extra


class Request:
    def __init__(self, environ: dict[str, Any], cfg: Config):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = environ.get("PATH_INFO", "/") or "/"
        self.query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
        self.ip = (environ.get("REMOTE_ADDR") or "")[:64]
        self.user_agent = environ.get("HTTP_USER_AGENT", "")[:200]
        cookie = SimpleCookie()
        try:
            cookie.load(environ.get("HTTP_COOKIE", ""))
        except CookieError:
            cookie = SimpleCookie()  # a malformed cookie header is treated as no cookie
        name = cookie_name(cfg)
        self.session_token = cookie[name].value if name in cookie else None
        self._body: bytes | None = None
        self.cfg = cfg

    def body(self, limit: int = MAX_JSON_BYTES) -> bytes:
        if self._body is None:
            try:
                length = int(self.environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = 0
            if length > limit:
                raise HttpError(413, "too_large", "حجم الطلب أكبر من المسموح.")
            self._body = self.environ["wsgi.input"].read(length) if length > 0 else b""
        return self._body

    def json(self, limit: int = MAX_JSON_BYTES) -> dict[str, Any]:
        ctype = self.environ.get("CONTENT_TYPE", "")
        if not ctype.startswith("application/json"):
            raise HttpError(415, "json_required", "يجب إرسال JSON.")
        try:
            data = json.loads(self.body(limit).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise HttpError(400, "bad_json", "JSON غير صالح.") from None
        if not isinstance(data, dict):
            raise HttpError(400, "bad_json", "JSON غير صالح.")
        return data


Handler = Callable[..., Any]


class App:
    def __init__(self, cfg: Config | None = None, db: Database | None = None):
        # validate() refuses to start with dev mode / insecure cookies outside development
        self.cfg = (cfg or Config.from_env()).validate()
        self.db = db or Database(self.cfg.db_path)
        self.routes: list[tuple[str, re.Pattern[str], Handler, str]] = []
        r = self._route
        # access: "public" | "user" | "admin" | "webhook"
        r("GET", r"/api/health", self.health, "public")
        r("GET", r"/api/plans", self.plans, "public")
        r("GET", r"/api/dashboard", self.dashboard, "public")
        r("GET", r"/api/research", self.research, "public")
        r("POST", r"/api/auth/register", self.register, "public")
        r("POST", r"/api/auth/login", self.login, "public")
        r("POST", r"/api/auth/verify", self.verify, "public")
        r("POST", r"/api/auth/reset-request", self.reset_request, "public")
        r("POST", r"/api/auth/reset", self.reset, "public")
        r("POST", r"/api/auth/logout", self.logout, "user")
        r("POST", r"/api/auth/logout-all", self.logout_all, "user")
        r("GET", r"/api/me", self.me, "user")
        r("GET", r"/api/sessions", self.sessions, "user")
        r("DELETE", r"/api/sessions/(?P<sid>\d+)", self.revoke_session, "user")
        r("POST", r"/api/account/password", self.change_password, "user")
        r("GET", r"/api/account/export", self.export, "user")
        r("POST", r"/api/account/delete", self.delete_account, "user")
        r("GET", r"/api/watchlists", self.watchlists, "user")
        r("POST", r"/api/watchlists", self.create_watchlist, "user")
        r("GET", r"/api/watchlists/(?P<wid>\d+)", self.get_watchlist, "user")
        r("PATCH", r"/api/watchlists/(?P<wid>\d+)", self.rename_watchlist, "user")
        r("DELETE", r"/api/watchlists/(?P<wid>\d+)", self.delete_watchlist, "user")
        r("POST", r"/api/watchlists/(?P<wid>\d+)/symbols", self.add_symbol, "user")
        r("DELETE", r"/api/watchlists/(?P<wid>\d+)/symbols/(?P<symbol>[A-Za-z0-9.\-]{1,10})", self.remove_symbol, "user")
        r("GET", r"/api/datasets", self.datasets, "user")
        r("POST", r"/api/datasets", self.upload_dataset, "user")
        r("DELETE", r"/api/datasets/(?P<did>\d+)", self.delete_dataset, "user")
        r("GET", r"/api/datasets/(?P<did>\d+)/analysis", self.analyse, "user")
        r("GET", r"/api/backtests", self.backtests, "user")
        r("POST", r"/api/backtests", self.run_backtest, "user")
        r("GET", r"/api/backtests/(?P<bid>\d+)", self.get_backtest, "user")
        r("POST", r"/api/billing/webhook", self.billing_webhook, "webhook")
        r("GET", r"/api/admin/overview", self.admin_overview, "admin")
        r("POST", r"/api/admin/grant", self.admin_grant, "admin")

    def _route(self, method: str, pattern: str, handler: Handler, access: str) -> None:
        self.routes.append((method, re.compile(f"^{pattern}$"), handler, access))

    # ------------------------------------------------------------ WSGI entry

    def __call__(self, environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        if not self.cfg.enabled:
            return self._send(start_response, 404, b"Not Found", "text/plain; charset=utf-8")
        req = Request(environ, self.cfg)
        try:
            if req.path.startswith("/api/"):
                status, payload, extra_headers = self._api(req)
                body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
                return self._send(start_response, status, body, "application/json; charset=utf-8", extra_headers)
            return self._static(req, start_response)
        except HttpError as err:
            body = json.dumps({"error": err.code, "message_ar": err.message_ar, **err.extra},
                              ensure_ascii=False).encode("utf-8")
            return self._send(start_response, err.status, body, "application/json; charset=utf-8")
        except Exception as exc:  # noqa: BLE001 - last-resort handler; nothing sensitive leaves
            # Log only the exception type and the path (no message, body, headers,
            # cookies or query string, which may hold tokens or personal data).
            LOG.error("unhandled %s on %s %s", type(exc).__name__, req.method, req.path[:120])
            body = json.dumps({"error": "server_error", "message_ar": "خطأ داخلي؛ لم يُحفظ أي تغيير غير مكتمل."},
                              ensure_ascii=False).encode("utf-8")
            return self._send(start_response, 500, body, "application/json; charset=utf-8")

    def _send(self, start_response: Callable, status: int, body: bytes, ctype: str,
              extra: list[tuple[str, str]] | None = None) -> list[bytes]:
        headers = [("Content-Type", ctype), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                   *SECURITY_HEADERS, *(extra or [])]
        start_response(f"{status} {HTTPStatus(status).phrase}", headers)
        return [body]

    def _static(self, req: Request, start_response: Callable) -> list[bytes]:
        if req.method != "GET":
            raise HttpError(405, "method_not_allowed", "طريقة غير مسموحة.")
        name = "index.html" if req.path in ("/", "/index.html") else req.path.removeprefix("/static/")
        if name != "index.html" and (not req.path.startswith("/static/") or name not in STATIC_FILES):
            return self._send(start_response, 404, b"Not Found", "text/plain; charset=utf-8")
        path = Path(self.cfg.ui_dir) / name
        ctype = (mimetypes.guess_type(name)[0] or "application/octet-stream") + "; charset=utf-8"
        return self._send(start_response, 200, path.read_bytes(), ctype)

    def _check_origin(self, req: Request) -> None:
        # Browsers send Sec-Fetch-Site on every request; "cross-site" is refused even
        # when Origin is absent. Non-browser clients send neither and carry no
        # victim cookies, so they are judged by the session/CSRF checks alone.
        if req.environ.get("HTTP_SEC_FETCH_SITE", "").lower() == "cross-site":
            raise HttpError(403, "cross_origin", "طلب من موقع آخر مرفوض.")
        origin = req.environ.get("HTTP_ORIGIN")
        if not origin:
            return
        host = req.environ.get("HTTP_HOST") or req.environ.get("SERVER_NAME", "")
        if origin == "null" or urlparse(origin).netloc != host:
            raise HttpError(403, "cross_origin", "طلب من موقع آخر مرفوض.")

    def _api(self, req: Request) -> tuple[int, Any, list[tuple[str, str]]]:
        allowed_methods = set()
        for method, pattern, handler, access in self.routes:
            m = pattern.match(req.path)
            if not m:
                continue
            allowed_methods.add(method)
            if method != req.method:
                continue
            mutating = method in ("POST", "PATCH", "DELETE")
            user: SessionUser | None = None
            if access != "webhook":
                if mutating:
                    self._check_origin(req)
                user = accounts.user_for_token(self.db, req.session_token, idle_hours=self.cfg.session_idle_hours)
                if access in ("user", "admin") and user is None:
                    raise HttpError(401, "login_required", "سجّل الدخول أولًا.")
                # Admin needs role + verified e-mail + a recorded server-side grant.
                if access == "admin" and (user is None or not user.is_admin):
                    # not 403: do not advertise the admin surface
                    raise HttpError(404, "not_found", "غير موجود.")
                if mutating and user is not None and req.environ.get("HTTP_X_CSRF_TOKEN") != user.csrf_token:
                    raise HttpError(403, "csrf", "رمز الحماية مفقود أو غير صحيح؛ أعد تحميل الصفحة.")
            try:
                result = handler(req, user, **m.groupdict())
            except AccountError as err:
                raise HttpError(err.status, "request_failed", err.message_ar) from None
            except EntitlementError as err:
                raise HttpError(403, "plan_required", err.message_ar, feature=err.feature, limit=err.limit) from None
            except backtest.BacktestError as err:
                raise HttpError(400, "invalid_backtest", err.message_ar) from None
            if isinstance(result, tuple):
                return result
            return 200, result, []
        if allowed_methods:
            raise HttpError(405, "method_not_allowed", "طريقة غير مسموحة.")
        raise HttpError(404, "not_found", "غير موجود.")

    def _cookie(self, token: str, max_age: int) -> tuple[str, str]:
        parts = [f"{cookie_name(self.cfg)}={token}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"]
        if self.cfg.secure_cookies:
            parts.append("Secure")
        return ("Set-Cookie", "; ".join(parts))

    # ------------------------------------------------------------ handlers

    def health(self, req, user):
        return {"ok": True, "billing_mode": self.cfg.billing_mode, "schema": 1}

    def plans(self, req, user):
        return {"plans": accounts.plans_catalog(), "billing_mode": self.cfg.billing_mode,
                "note_ar": "الأسعار فرضيات تجريبية للاختبار مع العملاء؛ لا يوجد تحصيل مالي في هذه النسخة."}

    def dashboard(self, req, user):
        out = research.dashboard(self.cfg)
        if user is not None:
            out["workspace"] = {"watchlists": len(workspace.list_watchlists(self.db, user)),
                                "datasets": len(workspace.list_datasets(self.db, user))}
        return out

    def research(self, req, user):
        symbols = None
        if req.query.get("watchlist"):
            if user is None:
                raise HttpError(401, "login_required", "سجّل الدخول أولًا.")
            wl = workspace.get_watchlist(self.db, user, req.query["watchlist"])
            symbols = [s["symbol"] for s in wl["symbols"]]
        return research.research_center(self.cfg, symbols=symbols)

    def register(self, req, user):
        data = req.json()
        return 201, accounts.register(self.db, self.cfg, email=data.get("email"), password=data.get("password"),
                                      display_name=data.get("display_name"), consent=data.get("consent"),
                                      ip=req.ip), []

    def login(self, req, user):
        data = req.json()
        token, session_user = accounts.login(self.db, self.cfg, email=data.get("email"),
                                             password=data.get("password"), ip=req.ip, user_agent=req.user_agent)
        payload = {"user": session_user.public(self.db), "csrf_token": session_user.csrf_token}
        return 200, payload, [self._cookie(token, self.cfg.session_hours * 3600)]

    def verify(self, req, user):
        accounts.verify_email(self.db, self.cfg, req.json().get("token"), ip=req.ip)
        return {"ok": True}

    def reset_request(self, req, user):
        return accounts.request_reset(self.db, self.cfg, email=req.json().get("email"), ip=req.ip)

    def reset(self, req, user):
        data = req.json()
        accounts.reset_password(self.db, self.cfg, token=data.get("token"), new=data.get("password"), ip=req.ip)
        return {"ok": True}

    def logout(self, req, user):
        accounts.logout(self.db, user, ip=req.ip)
        return 200, {"ok": True}, [self._cookie("", 0)]

    def logout_all(self, req, user):
        accounts.logout(self.db, user, everywhere=True, ip=req.ip)
        return 200, {"ok": True}, [self._cookie("", 0)]

    def me(self, req, user):
        return {"user": user.public(self.db), "csrf_token": user.csrf_token}

    def sessions(self, req, user):
        return {"sessions": accounts.list_sessions(self.db, user)}

    def revoke_session(self, req, user, sid):
        accounts.revoke_session(self.db, user, sid, ip=req.ip)
        return {"ok": True}

    def change_password(self, req, user):
        data = req.json()
        accounts.change_password(self.db, user, current=data.get("current"), new=data.get("new"), ip=req.ip)
        return {"ok": True}

    def export(self, req, user):
        return 200, accounts.export_data(self.db, user), [
            ("Content-Disposition", 'attachment; filename="ghazi-platform-export.json"')]

    def delete_account(self, req, user):
        accounts.delete_account(self.db, user, password=req.json().get("password"), ip=req.ip)
        return 200, {"ok": True}, [self._cookie("", 0)]

    def watchlists(self, req, user):
        return {"watchlists": workspace.list_watchlists(self.db, user)}

    def create_watchlist(self, req, user):
        return 201, workspace.create_watchlist(self.db, user, req.json().get("name"), ip=req.ip), []

    def get_watchlist(self, req, user, wid):
        return workspace.get_watchlist(self.db, user, wid)

    def rename_watchlist(self, req, user, wid):
        return workspace.rename_watchlist(self.db, user, wid, req.json().get("name"), ip=req.ip)

    def delete_watchlist(self, req, user, wid):
        workspace.delete_watchlist(self.db, user, wid, ip=req.ip)
        return {"ok": True}

    def add_symbol(self, req, user, wid):
        data = req.json()
        return workspace.add_symbol(self.db, user, wid, data.get("symbol"), data.get("note"), ip=req.ip)

    def remove_symbol(self, req, user, wid, symbol):
        return workspace.remove_symbol(self.db, user, wid, symbol, ip=req.ip)

    def datasets(self, req, user):
        return {"datasets": workspace.list_datasets(self.db, user)}

    def upload_dataset(self, req, user):
        data = req.json(limit=self.cfg.max_upload_bytes)
        return 201, workspace.upload_dataset(self.db, user, symbol=data.get("symbol"), label=data.get("label"),
                                             csv_text=data.get("csv"), rights_attested=data.get("rights_attested"),
                                             ip=req.ip), []

    def delete_dataset(self, req, user, did):
        workspace.delete_dataset(self.db, user, did, ip=req.ip)
        return {"ok": True}

    def analyse(self, req, user, did):
        require_feature(workspace.plan_for(self.db, user), "analysis")
        meta, bars = workspace.dataset_bars(self.db, user, did)
        return analysis.analyse_user_bars(meta["symbol"], bars, dataset_label=meta["label"])

    def backtests(self, req, user):
        rows = self.db.query("SELECT id, dataset_id, strategy, created_at FROM backtests WHERE user_id=? AND status='done'"
                             " ORDER BY id DESC LIMIT 50", (user.id,))
        return {"backtests": [dict(r) for r in rows], "strategies": {k: {"name_ar": v["name_ar"], "params": {
            p: {"min": lo, "max": hi, "default": d} for p, (lo, hi, d) in v["params"].items()}}
            for k, v in backtest.STRATEGIES.items()}}

    def run_backtest(self, req, user):
        plan = workspace.plan_for(self.db, user)
        require_feature(plan, "backtest_lab")
        data = req.json()
        meta, bars = workspace.dataset_bars(self.db, user, data.get("dataset_id"))
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        strategy = str(data.get("strategy") or "")
        if params.get("oos_fraction") not in (None, 0, 0.0, "0", ""):
            require_feature(plan, "backtest_oos_split")
        backtest.validate(strategy, params)  # reject bad input before a quota slot is used
        since = iso(utcnow() - timedelta(hours=24))
        with self.db.tx() as conn:
            # Reserve the quota slot under the write lock, before the slow run: concurrent
            # requests cannot all see the same count and exceed the daily limit.
            used = conn.execute("SELECT COUNT(*) FROM backtests WHERE user_id=? AND created_at>=?",
                                (user.id, since)).fetchone()[0]
            require_below(used, plan.backtests_per_day, "عدد الاختبارات اليومية", "backtests_per_day")
            bid = conn.execute("INSERT INTO backtests(user_id, dataset_id, strategy, params_json, result_json, status,"
                               " created_at) VALUES (?,?,?,'{}','{}','running',?)",
                               (user.id, meta["id"], strategy, iso(utcnow()))).lastrowid
        try:
            result = backtest.run(strategy, bars, params,
                                  allow_oos="backtest_oos_split" in plan.features,
                                  allow_cost_sensitivity="backtest_cost_sensitivity" in plan.features)
        except Exception:
            with self.db.tx() as conn:
                conn.execute("DELETE FROM backtests WHERE id=? AND user_id=?", (bid, user.id))
            raise
        result["dataset"] = {"id": meta["id"], "symbol": meta["symbol"], "label": meta["label"]}
        with self.db.tx() as conn:
            conn.execute("UPDATE backtests SET params_json=?, result_json=?, status='done' WHERE id=? AND user_id=?",
                         (json.dumps(result["params"]), json.dumps(result), bid, user.id))
        audit.record(self.db, "backtest.run", user_id=user.id, ip=req.ip, backtest=bid, strategy=result["strategy"])
        result["id"] = bid
        return 201, result, []

    def get_backtest(self, req, user, bid):
        row = self.db.one("SELECT result_json FROM backtests WHERE id=? AND user_id=? AND status='done'",
                          (int(bid), user.id))
        if not row:
            raise HttpError(404, "not_found", "الاختبار غير موجود.")
        return {**json.loads(row["result_json"]), "id": int(bid)}

    def billing_webhook(self, req, user):
        status, payload = billing.handle_webhook(self.db, self.cfg, req.body(),
                                                 req.environ.get("HTTP_X_GHAZI_SIGNATURE", ""))
        return status, payload, []

    def admin_overview(self, req, user):
        return billing.admin_overview(self.db)

    def admin_grant(self, req, user):
        data = req.json()
        return billing.admin_grant(self.db, actor_id=user.id, user_id=data.get("user_id"), plan=data.get("plan"),
                                   days=data.get("days"), ip=req.ip)


def create_app(**overrides: Any) -> App:
    return App(Config.from_env(**overrides))
