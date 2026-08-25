from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


MAX_BODY_BYTES = 64_000
TELEGRAM_TIMEOUT_SECONDS = 1.8


def _safe(value, default="-") -> str:
    if value is None or value == "":
        return default
    return str(value)


def _first(payload: dict, *names: str):
    for name in names:
        if name in payload and payload[name] is not None:
            return payload[name]
    return None


def _direction_ar(value: str) -> str:
    value = value.strip().lower()
    if value in {"call", "bull"}:
        return "كول"
    if value in {"put", "bear"}:
        return "بوت"
    return "-"


def _telegram_send(text: str) -> tuple[bool, str]:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return False, "telegram_not_configured"

    body = urlencode(
        {
            "chat_id": chat_id,
            "text": text[:4096],
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    req = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
    )
    try:
        with urlopen(req, timeout=TELEGRAM_TIMEOUT_SECONDS) as response:
            raw = response.read(4096)
        result = json.loads(raw.decode("utf-8")) if raw else {}
        return bool(result.get("ok")), "ok" if result.get("ok") else "telegram_rejected"
    except Exception as exc:  # Vercel log keeps the concrete error; response stays minimal.
        print(f"SNIPER telegram error: {type(exc).__name__}: {exc}")
        return False, "telegram_error"


class handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        configured = (os.getenv("SNIPER_WEBHOOK_SECRET") or "").strip()
        if not configured:
            return True
        query = parse_qs(urlparse(self.path).query)
        supplied = (query.get("secret") or [""])[0]
        return hmac.compare_digest(configured, supplied)

    def do_GET(self):  # noqa: N802
        self._reply(
            200,
            {
                "status": "ok",
                "service": "sniper-webhook",
                "telegram_configured": bool(
                    (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
                    and (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
                ),
                "secret_required": bool((os.getenv("SNIPER_WEBHOOK_SECRET") or "").strip()),
            },
        )

    def do_POST(self):  # noqa: N802
        if not self._authorized():
            self._reply(401, {"status": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._reply(400, {"status": "bad_request", "error": "invalid_payload_size"})
            return

        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")
        except Exception:
            self._reply(400, {"status": "bad_request", "error": "invalid_json"})
            return

        event = _safe(payload.get("event"), "signal").strip().lower()
        direction = _safe(payload.get("direction"), "").strip().lower()
        symbol = _safe(payload.get("symbol"), "").strip().upper()
        if event not in {"signal", "call", "put", "setup", "invalidation", "target"}:
            self._reply(400, {"status": "bad_request", "error": "unsupported_event"})
            return
        if not symbol:
            self._reply(400, {"status": "bad_request", "error": "symbol_required"})
            return
        if direction not in {"call", "put", "bull", "bear", "none", ""}:
            self._reply(400, {"status": "bad_request", "error": "unsupported_direction"})
            return

        score = _safe(payload.get("score"), "0")
        target1 = _first(payload, "target1", "target_1")
        target2 = _first(payload, "target2", "target_2")
        target3 = _first(payload, "target3", "target_3")
        message = (
            "🎯 سنايبر × بلاك بوكس\n"
            f"السهم/المؤشر: {symbol}\n"
            f"الاتجاه: {_direction_ar(direction)}\n"
            f"الجودة: {score}/100\n"
            f"الأفق: {_safe(payload.get('horizon'))}\n"
            f"الفريم: {_safe(payload.get('timeframe'))}\n"
            f"الدخول: {_safe(payload.get('entry'))}\n"
            f"الإلغاء: {_safe(payload.get('stop'))}\n"
            f"الهدف 1: {_safe(target1)}\n"
            f"الهدف 2: {_safe(target2)}\n"
            f"الهدف 3: {_safe(target3)}\n"
            f"المحرك: {_safe(payload.get('engine'))}\n"
            f"حالة السوق: {_safe(payload.get('regime'))}\n"
            f"السبب: {_safe(payload.get('reason'))}"
        )

        sent, detail = _telegram_send(message)
        if sent:
            self._reply(200, {"status": "ok", "accepted": True, "telegram": "sent"})
        else:
            self._reply(503, {"status": "accepted_but_not_delivered", "detail": detail})
