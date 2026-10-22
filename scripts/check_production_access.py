"""External, non-price access smoke for GHAZI RADAR production and Telegram bot.

This checks *actual HTTP* availability from a Github-hosted runner. Vercel READY
does not prove an HTTP route is accessible and Telegram getMe does not prove
message delivery. Never echo bot tokens or raw upstream HTTP responses.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAIN = "https://ghazibot.vercel.app"
SECONDARY = "https://ghazir.vercel.app"
MAX_HTML_BYTES = 400_000
SCHEMA = "ghazi.production_access.v1"
PAGES = (
    ("homepage", MAIN + "/", "text/html", b"GHAZI RADAR"),
    ("catalyst_desk", MAIN + "/catalyst-desk.html", "text/html", b"Official Catalyst Desk"),
    ("github_50", MAIN + "/github-projects.html", "text/html", b"50"),
    ("secondary_alias", SECONDARY + "/", "text/html", b"GHAZI RADAR"),
    ("site_health", MAIN + "/health", "application/json", b""),
    ("site_data_status", MAIN + "/data-status", "application/json", b""),
)


def get_response(url: str, *, fetch: Any = urlopen) -> tuple[int, str, str, bytes]:
    """Only two allowlisted origins or the official Telegram getMe endpoint."""
    if not (url.startswith((MAIN + "/", SECONDARY + "/")) or
            (url.startswith("https://api.telegram.org/bot") and url.endswith("/getMe"))):
        raise ValueError("URL outside access-probe allowlist")
    request = Request(url, headers={
        "User-Agent": "GHAZI-RADAR-Access-Smoke/1.0 (+GitHub-Actions)",
        "Cache-Control": "no-cache",
        "Accept": "text/html,application/json,text/plain,*/*",
    })
    with fetch(request, timeout=14, context=ssl.create_default_context()) as response:
        # Do not expose the Telegram URL (includes credential) in any output.
        status = int(response.status)
        final_url = str(response.geturl())
        mime = response.headers.get("Content-Type", "").lower().split(";")[0].strip()
        payload = response.read(MAX_HTML_BYTES + 1)
    return status, final_url, mime, payload


def check_site(*, fetch: Any = urlopen) -> list[dict[str, Any]]:
    results = []
    for key, url, mime, marker in PAGES:
        evidence = {"key": key, "result": "UNREACHABLE", "http_status": None}
        try:
            code, final, actual, payload = get_response(url, fetch=fetch)
            evidence["http_status"] = code
            host = final.split("/", 3)[2].lower() if final.startswith("https://") else ""
            allowed = host in {"ghazibot.vercel.app", "ghazir.vercel.app"}
            if not allowed or code != 200:
                evidence["result"] = "WRONG_DESTINATION_OR_HTTP"
            elif len(payload) > MAX_HTML_BYTES or len(payload) < 16:
                evidence["result"] = "INVALID_RESPONSE_SIZE"
            elif actual != mime:
                evidence["result"] = "WRONG_CONTENT_TYPE"
            elif marker and marker not in payload:
                evidence["result"] = "CONTENT_MISMATCH"
            elif mime == "application/json":
                data = json.loads(payload)
                if not isinstance(data, dict) or not isinstance(data.get("status"), str):
                    evidence["result"] = "INVALID_JSON_SCHEMA"
                else:
                    # A static status JSON is proof of accessibility, not proof
                    # the underlying prices or source freshness are verified.
                    evidence["result"] = "ACCESSIBLE"
                    evidence["reported_data_status"] = data["status"][:30]
            else:
                evidence["result"] = "ACCESSIBLE"
        except HTTPError as error:
            evidence["result"] = "HTTP_ERROR"
            evidence["http_status"] = error.code
        except (URLError, ValueError, TypeError, OSError, KeyError, IndexError):
            evidence["result"] = "REQUEST_FAILED"
        results.append(evidence)
    return results


def check_telegram(token: str, *, fetch: Any = urlopen) -> dict[str, Any]:
    if not token:
        return {"result": "TOKEN_NOT_CONFIGURED", "bot_api_authenticated": False,
                "message_delivery_proven": False}
    if any(ch in token for ch in ("/", "?", "#", " ", "\n")) or len(token) > 200:
        return {"result": "INVALID_TOKEN_FORMAT", "bot_api_authenticated": False,
                "message_delivery_proven": False}
    try:
        code, final, mime, body = get_response(
            "https://api.telegram.org/bot" + token + "/getMe", fetch=fetch
        )
        # Never emit final URL, response content, bot name, token, or exception
        # text: those can all contain private identifiers.
        parsed = json.loads(body)
        valid = (
            code == 200 and final.startswith("https://api.telegram.org/") and
            mime == "application/json" and len(body) <= MAX_HTML_BYTES and
            isinstance(parsed, dict) and parsed.get("ok") is True and
            isinstance(parsed.get("result"), dict) and parsed["result"].get("is_bot") is True
        )
    except (HTTPError, URLError, ValueError, TypeError, OSError, KeyError):
        valid = False
    return {"result": "AUTHENTICATED" if valid else "NOT_VERIFIED",
            "bot_api_authenticated": valid,
            "message_delivery_proven": False}


def audit(*, now: datetime, token: str = "", fetch: Any = urlopen) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("timezone-aware time required")
    pages = check_site(fetch=fetch)
    bot = check_telegram(token, fetch=fetch)
    ok = all(row["result"] == "ACCESSIBLE" for row in pages)
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "status": "ACCESSIBLE" if ok and bot["bot_api_authenticated"] else (
            "SITE_ACCESSIBLE_BOT_UNVERIFIED" if ok else "SITE_HTTP_PROBE_FAILED"
        ),
        "site_http_accessible": ok,
        "bot_api_authenticated": bot["bot_api_authenticated"],
        "telegram_delivery_verified_by_this_check": False,
        "bot": bot,
        "pages": pages,
        "market_data_authority": False,
        "options_execution_authority": False,
        "notes_ar": (
            "فحص HTTP من GitHub Actions للتحقق من صفحات الموقع وهوية Telegram فقط. "
            "لا يثبت صلاحية المصادر السعرية، أو وصول رسالة إلى المستخدم، أو نجاح صفقة."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(now=datetime.now(timezone.utc), token=os.getenv("TELEGRAM_BOT_TOKEN", ""))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    temp.replace(args.output)
    print("GHAZI production access:", result["status"],
          "site reachable:", result["site_http_accessible"],
          "Telegram bot authenticated:", result["bot_api_authenticated"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
