from __future__ import annotations

import hmac
import json
import logging
import os
import threading
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from options_radar.black_box_bot import BlackBoxBot

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
LOGGER = logging.getLogger(__name__)
BOT = BlackBoxBot()


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")


class Handler(SimpleHTTPRequestHandler):
    server_version = "GHAZI-BlackBox/1.0"

    def _reply(self, status: int, payload: dict[str, Any]) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        configured = BOT.config.webhook_secret
        if not configured:
            return True
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        supplied = self.headers.get("X-Sniper-Secret") or (query.get("secret") or [""])[0]
        return hmac.compare_digest(str(configured), str(supplied))

    def end_headers(self) -> None:
        if self.path.startswith("/data/") or self.path.endswith("latest.json"):
            self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._reply(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "service": "black-box-sniper-bot",
                    "telegram_configured": BOT.notifier.configured,
                    "scanner_enabled": BOT.config.enabled,
                    "last_scan": BOT.last_snapshot,
                },
            )
            return
        if parsed.path == "/scan/latest":
            self._reply(HTTPStatus.OK, BOT.last_snapshot or {"status": "not_run"})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in {"/webhook/sniper", "/webhook/tradingview"}:
            self._reply(HTTPStatus.NOT_FOUND, {"status": "not_found"})
            return
        if not self._authorized():
            self._reply(HTTPStatus.UNAUTHORIZED, {"status": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64_000:
                raise ValueError("invalid payload size")
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")
            result = BOT.handle_sniper(payload)
            self._reply(HTTPStatus.OK, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self._reply(HTTPStatus.BAD_REQUEST, {"status": "bad_request", "error": str(exc)})
        except Exception as exc:
            LOGGER.exception("Webhook processing failed")
            self._reply(HTTPStatus.INTERNAL_SERVER_ERROR, {"status": "error", "error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), fmt % args)


def main() -> int:
    if BOT.config.enabled:
        worker = threading.Thread(target=BOT.run_forever, name="black-box-scanner", daemon=True)
        worker.start()
    port = int(os.getenv("PORT", "10000"))
    public_dir = Path(__file__).resolve().parent / "public"
    handler = partial(Handler, directory=str(public_dir))
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    LOGGER.info("Black Box bot + dashboard listening on 0.0.0.0:%s", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Server stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
