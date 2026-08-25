from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from options_radar.catalysts import CatalystScanner
from options_radar.providers import load_universe
from options_radar.settings import Settings
from scripts.telegram_transport import send_html_message


def _safe(value: Any, limit: int = 360) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return html.escape(text)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sent": {}}
    return raw if isinstance(raw, dict) else {"sent": {}}


def _save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _fingerprint(row: pd.Series) -> str:
    raw = "|".join(
        str(row.get(key) or "")
        for key in ("symbol", "event_date", "category", "headline", "source", "form", "url")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _format(row: pd.Series) -> str:
    score = _number(row.get("score"))
    icon = "🟢" if score > 0 else "🔴" if score < 0 else "🟡"
    direction = "إيجابي" if score > 0 else "سلبي" if score < 0 else "محايد"
    lines = [
        f"{icon} <b>BLACK BOX | خبر جوهري | {_safe(row.get('symbol'), 20)}</b>",
        f"📰 {_safe(row.get('headline'), 520)}",
        f"التصنيف: <b>{_safe(row.get('category'), 140)}</b> | الأثر الخام: <b>{score:+.0f}</b> ({direction})",
        f"المصدر: <b>{_safe(row.get('source'), 120)}</b> | التاريخ: {_safe(row.get('event_date'), 24)}",
    ]
    form = str(row.get("form") or "").strip()
    evidence = str(row.get("evidence") or "").strip()
    if form:
        lines.append(f"النموذج/النوع: {_safe(form, 60)}")
    if evidence:
        lines.append(f"الدليل: {_safe(evidence, 300)}")
    url = str(row.get("url") or "").strip()
    if url.startswith("https://"):
        lines.append(f'<a href="{html.escape(url, quote=True)}">فتح المصدر</a>')
    lines.append("<i>تنبيه معلوماتي؛ لا يغيّر أهلية إشارة السهم أو العقد بمفرده.</i>")
    return "\n".join(lines)


def send_news(frame: pd.DataFrame, state: dict[str, Any]) -> int:
    if frame is None or frame.empty:
        state.update({"last_run_at": datetime.now(timezone.utc).isoformat(), "last_sent_count": 0})
        return 0

    minimum = abs(_number(os.getenv("NEWS_ALERT_MIN_ABS_SCORE", "15"), 15.0))
    maximum = max(1, min(10, int(_number(os.getenv("NEWS_ALERT_MAX_PER_RUN", "5"), 5))))
    sent_map = state.setdefault("sent", {})
    if not isinstance(sent_map, dict):
        sent_map = {}
        state["sent"] = sent_map

    candidates = frame[pd.to_numeric(frame.get("score"), errors="coerce").abs() >= minimum].copy()
    if candidates.empty:
        state.update({"last_run_at": datetime.now(timezone.utc).isoformat(), "last_sent_count": 0, "minimum_abs_score": minimum})
        return 0

    candidates["abs_score"] = pd.to_numeric(candidates["score"], errors="coerce").abs()
    candidates = candidates.sort_values(["abs_score", "event_date"], ascending=[False, False])

    sent = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for _, row in candidates.iterrows():
        if sent >= maximum:
            break
        fp = _fingerprint(row)
        if fp in sent_map:
            continue
        result = send_html_message(_format(row))
        sent_map[fp] = {
            "sent_at": now_iso,
            "message_id": getattr(result, "message_id", None),
            "symbol": str(row.get("symbol") or ""),
            "headline": str(row.get("headline") or "")[:240],
        }
        sent += 1

    if len(sent_map) > 1200:
        ordered = sorted(
            sent_map.items(),
            key=lambda item: str(item[1].get("sent_at") if isinstance(item[1], dict) else ""),
            reverse=True,
        )[:900]
        state["sent"] = dict(ordered)

    state.update(
        {
            "last_run_at": now_iso,
            "last_sent_count": sent,
            "minimum_abs_score": minimum,
            "state_schema": "material_news_registry_v1",
        }
    )
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Send deduplicated material company/catalyst alerts to BLACK BOX Telegram")
    parser.add_argument("--universe", default="data/universe.txt")
    parser.add_argument("--state", default="data/live/sniper_news_alert_state.json")
    parser.add_argument("--lookback-days", type=int, default=3)
    parser.add_argument("--max-symbols", type=int, default=120)
    args = parser.parse_args()

    settings = Settings()
    settings.validate()
    symbols = load_universe(args.universe)[: max(1, min(args.max_symbols, settings.max_universe_size))]
    if not symbols:
        raise RuntimeError("News watch universe is empty")

    frame = CatalystScanner(settings).scan(symbols, lookback_days=max(1, args.lookback_days))
    state_path = Path(args.state)
    state = _load(state_path)
    try:
        sent = send_news(frame, state)
    finally:
        _save(state_path, state)
    print(f"Material news sender: symbols={len(symbols)} events={len(frame)} sent={sent}")


if __name__ == "__main__":
    main()
