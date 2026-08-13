from __future__ import annotations

import argparse
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

RANK = {"HEALTHY": 0, "DEGRADED": 1, "CRITICAL": 2}


def _load(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(destination)


def _send(text: str) -> None:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        raise RuntimeError("Telegram destination is not ready")
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"},
        timeout=20,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram rejected radar-health message")


def maybe_send(path_name: str, payload: dict[str, Any], state: dict[str, Any]) -> bool:
    health = payload.get("health") if isinstance(payload.get("health"), dict) else {}
    current = str(health.get("status") or "UNKNOWN").upper()
    if current not in RANK:
        return False
    states = state.setdefault("paths", {})
    previous = str((states.get(path_name) or {}).get("status") or "UNKNOWN").upper()
    changed = previous != current
    should_send = changed and (current != "HEALTHY" or previous in {"DEGRADED", "CRITICAL"})
    if should_send:
        title = "🚨" if current == "CRITICAL" else ("⚠️" if current == "DEGRADED" else "✅")
        label = "مسار الأسهم" if path_name == "stocks" else "مسار عقود الأوبشن"
        reasons = [str(item) for item in health.get("reasons", []) if str(item).strip()]
        lines = [
            f"{title} <b>بلاك بوكس Ω — صحة النظام</b>",
            "",
            f"{html.escape(label)}: <b>{html.escape(current)}</b>",
        ]
        if previous in RANK:
            lines.append(f"الحالة السابقة: {html.escape(previous)}")
        for reason in reasons[:5]:
            lines.append(f"• {html.escape(reason[:360])}")
        if current == "HEALTHY":
            lines.append("✅ عاد المسار إلى الحالة السليمة.")
        else:
            lines.append("ℹ️ التنبيه يصف جودة/توفر البيانات؛ لا يعني وجود فرصة سوقية.")
        _send("\n".join(lines))
    states[path_name] = {
        "status": current,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": health.get("metrics", {}),
    }
    return should_send


def main() -> None:
    parser = argparse.ArgumentParser(description="Notify only on BLACK BOX radar health transitions")
    parser.add_argument("--path", choices=("stocks", "options"), required=True)
    parser.add_argument("--payload", required=True)
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    payload = _load(args.payload)
    state = _load(args.state) or {"paths": {}}
    sent = maybe_send(args.path, payload, state)
    _save(args.state, state)
    print(f"Radar health transition: path={args.path} sent={int(sent)}")


if __name__ == "__main__":
    main()
