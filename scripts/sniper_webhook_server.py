from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from scripts.omega_sniper import format_omega_sniper_message
from scripts.sniper_signal import enrich_sniper_message, parse_sniper_event
from scripts.telegram_transport import edit_html_message, send_html_message

LOGGER = logging.getLogger(__name__)
MAX_BODY_BYTES = 16 * 1024
TRADINGVIEW_WEBHOOK_IPS = {"52.89.214.238", "34.212.75.30", "54.218.53.128", "52.32.178.7"}
WORKERS = max(1, min(4, int(os.getenv("SNIPER_WEBHOOK_WORKERS", "2"))))
_EXECUTOR = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="sniper-webhook")


class DedupeRegistry:
    def __init__(self, path: str | Path, ttl_seconds: int = 24 * 3600):
        self.path = Path(path)
        self.ttl_seconds = max(300, int(ttl_seconds))
        self._lock = threading.Lock()
        self._pending: set[str] = set()

    def _load(self) -> dict[str, float]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        now = time.time()
        return {
            str(key): float(value)
            for key, value in raw.items()
            if isinstance(value, (int, float)) and now - float(value) <= self.ttl_seconds
        }

    def _save(self, data: dict[str, float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def reserve(self, key: str) -> bool:
        with self._lock:
            data = self._load()
            if key in data or key in self._pending:
                return False
            self._pending.add(key)
            return True

    def complete(self, key: str) -> None:
        with self._lock:
            data = self._load()
            data[key] = time.time()
            self._pending.discard(key)
            self._save(data)

    def release(self, key: str) -> None:
        with self._lock:
            self._pending.discard(key)


def _event_fingerprint(payload: dict[str, Any]) -> str:
    fields = [
        payload.get("schema"),
        payload.get("symbol"),
        payload.get("ticker_id"),
        payload.get("direction"),
        payload.get("timeframe"),
        payload.get("event_time_ms") or payload.get("time_close_ms"),
        payload.get("entry"),
        payload.get("score"),
    ]
    raw = "|".join(str(value or "") for value in fields)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_REGISTRY = DedupeRegistry(
    os.getenv("SNIPER_WEBHOOK_STATE_PATH", "/tmp/sniper_webhook_state.json"),
    ttl_seconds=int(os.getenv("SNIPER_WEBHOOK_DEDUPE_TTL_SECONDS", str(24 * 3600))),
)


def _configured_secret() -> str:
    return str(os.getenv("SNIPER_WEBHOOK_SECRET") or "").strip()


def _telegram_ready() -> bool:
    return bool(
        str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        and str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    )


def _client_ip(handler: SimpleHTTPRequestHandler) -> str:
    forwarded = str(handler.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
    return forwarded or str(handler.client_address[0])


def _deliver(payload: dict[str, Any], fingerprint: str) -> None:
    try:
        event = parse_sniper_event(payload)
        base_text = format_omega_sniper_message(event)
        result = send_html_message(base_text)
        _REGISTRY.complete(fingerprint)
        message_id = getattr(result, "message_id", None)
        if message_id is None:
            return
        if str(os.getenv("SNIPER_ENRICH_ENABLED", "true")).strip().lower() in {
            "0",
            "false",
            "no",
            "off",
        }:
            return
        try:
            enriched = enrich_sniper_message(event, base_text)
            if enriched != base_text:
                edit_html_message(int(message_id), enriched)
        except Exception:
            LOGGER.exception("Sniper enrichment failed for %s", event.symbol)
    except Exception:
        _REGISTRY.release(fingerprint)
        LOGGER.exception("Sniper webhook delivery failed")


class SniperHandler(SimpleHTTPRequestHandler):
    server_version = "BLACKBOX-Sniper/1.0"

    def end_headers(self) -> None:
        # A subclass (main.py) may already have selected the dashboard cache policy.
        # Do not emit a second contradictory Cache-Control header.
        buffered = getattr(self, "_headers_buffer", [])
        has_cache_control = any(
            isinstance(header, (bytes, bytearray))
            and header.lower().startswith(b"cache-control:")
            for header in buffered
        )
        if not has_cache_control:
            path = urlparse(self.path).path
            if (
                path.startswith("/data/")
                or path.endswith("latest.json")
                or path.startswith("/webhooks/")
                or path == "/health"
            ):
                self.send_header("Cache-Control", "no-store, max-age=0")
            else:
                self.send_header("Cache-Control", "public, max-age=300")
        super().end_headers()

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/health":
            self._json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "black-box-sniper-webhook",
                    "secret_configured": bool(_configured_secret()),
                    "telegram_configured": _telegram_ready(),
                    "enrichment_enabled": str(
                        os.getenv("SNIPER_ENRICH_ENABLED", "true")
                    ).strip().lower()
                    not in {"0", "false", "no", "off"},
                },
            )
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) not in {2, 3} or parts[0] != "webhooks" or parts[1] != "sniper":
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return

        expected = _configured_secret()
        if expected:
            if len(parts) != 3 or not hmac.compare_digest(parts[2], expected):
                self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "forbidden"})
                return
        else:
            if len(parts) != 2 or _client_ip(self) not in TRADINGVIEW_WEBHOOK_IPS:
                self._json(
                    HTTPStatus.FORBIDDEN,
                    {"ok": False, "error": "tradingview_source_required"},
                )
                return
        if not _telegram_ready():
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "telegram_not_configured"},
            )
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            status = (
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE
                if length > MAX_BODY_BYTES
                else HTTPStatus.BAD_REQUEST
            )
            self._json(status, {"ok": False, "error": "invalid_body_size"})
            return
        if "application/json" not in str(self.headers.get("Content-Type") or "").lower():
            self._json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"ok": False, "error": "json_required"},
            )
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            event = parse_sniper_event(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": str(exc)[:160]},
            )
            return

        fingerprint = _event_fingerprint(payload)
        if not _REGISTRY.reserve(fingerprint):
            self._json(
                HTTPStatus.ACCEPTED,
                {
                    "ok": True,
                    "duplicate": True,
                    "symbol": event.symbol,
                    "direction": event.direction,
                },
            )
            return
        _EXECUTOR.submit(_deliver, payload, fingerprint)
        self._json(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "queued": True,
                "symbol": event.symbol,
                "direction": event.direction,
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        message = format % args
        secret = _configured_secret()
        if secret:
            message = message.replace(secret, "<redacted>")
        LOGGER.info("%s - %s", self.address_string(), message)


def main() -> int:
    public_dir = Path(__file__).resolve().parents[1] / "public"
    if not public_dir.exists():
        raise FileNotFoundError(f"Dashboard directory not found: {public_dir}")
    port = int(os.getenv("PORT", "10000"))
    handler = partial(SniperHandler, directory=str(public_dir))
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    LOGGER.info("Serving dashboard + Sniper webhook on 0.0.0.0:%s", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Sniper webhook server stopped")
    finally:
        server.server_close()
        _EXECUTOR.shutdown(wait=False, cancel_futures=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
