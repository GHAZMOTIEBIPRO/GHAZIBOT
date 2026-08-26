from __future__ import annotations

import argparse
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

AUTH_URL = "https://realtime-options.intrinio.com/auth"
WS_BASE = "wss://realtime-options.intrinio.com/socket/websocket"
CLIENT_INFORMATION = "GHAZIBOT-V9-Realtime-Preflight"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def authenticate_realtime(api_key: str, timeout: float = 6.0) -> tuple[int, str]:
    if not api_key:
        return 0, ""
    response = requests.get(
        AUTH_URL,
        params={"api_key": api_key},
        headers={"Client-Information": CLIENT_INFORMATION},
        timeout=timeout,
    )
    token = response.text.strip() if response.status_code == 200 else ""
    return int(response.status_code), token


def probe_websocket(token: str, timeout: float = 12.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "opened": False,
        "error": None,
        "close_code": None,
        "elapsed_seconds": 0.0,
    }
    if not token:
        result["error"] = "missing_auth_token"
        return result

    try:
        import websocket
    except ImportError:
        result["error"] = "websocket_client_not_installed"
        return result

    finished = threading.Event()
    started = time.monotonic()
    url = f"{WS_BASE}?vsn=1.0.0&token={quote(token, safe='')}"

    def on_open(ws: Any) -> None:
        result["opened"] = True
        finished.set()
        ws.close()

    def on_error(_ws: Any, error: Any) -> None:
        # Never persist the websocket URL/token. Error type is enough for the audit.
        result["error"] = type(error).__name__ if error is not None else "websocket_error"
        finished.set()

    def on_close(_ws: Any, status_code: Any, _message: Any) -> None:
        try:
            result["close_code"] = int(status_code) if status_code is not None else None
        except (TypeError, ValueError):
            result["close_code"] = None
        finished.set()

    app = websocket.WebSocketApp(url, on_open=on_open, on_error=on_error, on_close=on_close)
    thread = threading.Thread(
        target=lambda: app.run_forever(skip_utf8_validation=True),
        daemon=True,
        name="intrinio-opra-preflight",
    )
    thread.start()
    finished.wait(max(1.0, timeout))
    if not result["opened"] and result["error"] is None:
        result["error"] = "websocket_open_timeout"
    try:
        app.close()
    except Exception:
        pass
    thread.join(timeout=2.0)
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def run_preflight(api_key: str, websocket_timeout: float = 12.0) -> dict[str, Any]:
    report: dict[str, Any] = {
        "checked_at": _utc_now(),
        "provider": "Intrinio OPRA",
        "requested_mode": "realtime",
        "api_key_present": bool(api_key),
        "auth_http_status": None,
        "auth_ok": False,
        "websocket_open": False,
        "websocket_error": None,
        "status": "NOT_READY",
        "reason": "unknown",
    }
    if not api_key:
        report["reason"] = "missing_intrinio_api_key"
        return report

    try:
        status, token = authenticate_realtime(api_key)
    except requests.RequestException as exc:
        report["reason"] = f"auth_transport_{type(exc).__name__}"
        return report

    report["auth_http_status"] = status
    report["auth_ok"] = status == 200 and bool(token)
    if not report["auth_ok"]:
        report["reason"] = f"realtime_auth_http_{status or 'no_response'}"
        return report

    websocket_result = probe_websocket(token, timeout=websocket_timeout)
    report["websocket_open"] = bool(websocket_result.get("opened"))
    report["websocket_error"] = websocket_result.get("error")
    report["websocket_close_code"] = websocket_result.get("close_code")
    report["websocket_elapsed_seconds"] = websocket_result.get("elapsed_seconds")

    if report["websocket_open"]:
        report["status"] = "READY"
        report["reason"] = "realtime_opra_auth_and_websocket_ok"
    else:
        report["reason"] = "realtime_websocket_not_open"
    return report


def _save(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Intrinio realtime OPRA auth and websocket entitlement")
    parser.add_argument("--output", default="data/live/realtime_opra_preflight.json")
    parser.add_argument("--websocket-timeout", type=float, default=12.0)
    parser.add_argument("--soft-fail", action="store_true", help="Write NOT_READY result without failing GitHub Actions")
    args = parser.parse_args()

    report = run_preflight(
        os.getenv("INTRINIO_API_KEY", "").strip(),
        websocket_timeout=max(2.0, min(30.0, args.websocket_timeout)),
    )
    _save(args.output, report)

    # Safe summary: never print the API key, auth token, or websocket URL.
    print(
        "Intrinio realtime OPRA preflight: "
        f"status={report['status']} auth_http={report.get('auth_http_status')} "
        f"websocket_open={report.get('websocket_open')} reason={report.get('reason')}"
    )
    if report["status"] != "READY" and not args.soft_fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
