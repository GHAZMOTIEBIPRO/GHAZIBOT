from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

TIMEOUT = 20


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _telegram_url(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _write_github_env(key: str, value: str) -> None:
    env_path = str(os.getenv("GITHUB_ENV") or "").strip()
    if not env_path:
        return
    with open(env_path, "a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def _mask_github_value(value: str) -> None:
    # GitHub recognizes this workflow command and redacts later log appearances.
    if value:
        print(f"::add-mask::{value}")


def _discover_from_updates(token: str) -> str:
    response = requests.get(_telegram_url(token, "getUpdates"), timeout=TIMEOUT)
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        return ""
    for update in reversed(body.get("result") or []):
        if not isinstance(update, dict):
            continue
        message = update.get("message") or update.get("edited_message") or update.get("channel_post")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        if chat.get("id") is not None:
            return str(chat["id"])
    return ""


def bootstrap(connection_path: Path) -> int:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    configured = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    cached = _load_json(connection_path)
    cached_chat_id = str(cached.get("chat_id") or "").strip()

    source = ""
    chat_id = ""
    if configured:
        chat_id = configured
        source = "github_secret"
    elif cached_chat_id:
        chat_id = cached_chat_id
        source = "private_workflow_artifact"
    elif token:
        try:
            chat_id = _discover_from_updates(token)
            if chat_id:
                source = "telegram_getUpdates"
        except Exception as exc:
            print(f"Telegram bootstrap: getUpdates failed: {type(exc).__name__}: {exc}")

    if not token:
        print("Telegram bootstrap: TELEGRAM_BOT_TOKEN is missing.")
        _write_github_env("TELEGRAM_READY", "false")
        return 0

    if not chat_id:
        print(
            "Telegram bootstrap: no destination is known yet. The workflow will keep retrying automatically. "
            "Send /start or any message to the bot once; the next scheduled run will learn the chat and retain it privately."
        )
        _write_github_env("TELEGRAM_READY", "false")
        return 0

    # Mask before exporting to GITHUB_ENV so the destination never appears in later env dumps.
    _mask_github_value(chat_id)
    _write_json(
        connection_path,
        {
            "chat_id": chat_id,
            "resolved_at": _utc_now(),
            "source": source,
        },
    )
    _write_github_env("TELEGRAM_CHAT_ID", chat_id)
    _write_github_env("TELEGRAM_READY", "true")
    print(f"Telegram bootstrap: destination ready via {source}; destination value is masked in Actions logs.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Persist Telegram destination between GitHub Actions runs")
    parser.add_argument(
        "--connection-path",
        default="telegram_runtime/connection.json",
        help="Ephemeral file restored/uploaded only as a GitHub Actions artifact",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return bootstrap(Path(args.connection_path))


if __name__ == "__main__":
    raise SystemExit(main())
