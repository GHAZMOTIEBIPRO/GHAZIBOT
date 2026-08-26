from __future__ import annotations

import argparse
import html
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import pandas as pd

from options_radar.intrinio_realtime import IntrinioRealtimeAdapter, IntrinioRealtimeConfig
from options_radar.realtime_flow import RealtimeFlowEngine, RealtimeFlowService, ThesisSnapshot
from options_radar.telegram_transport import edit_html_message, send_html_message


DEFAULT_SYMBOLS = (
    "SPY",
    "QQQ",
    "IWM",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "TSLA",
    "META",
    "AMZN",
    "GOOGL",
    "AVGO",
)


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _market_window(*, wait_for_market: bool, max_wait_seconds: int) -> tuple[datetime, datetime] | None:
    calendar = xcals.get_calendar("XNYS")
    now = pd.Timestamp(datetime.now(timezone.utc)).floor("min")
    try:
        if bool(calendar.is_open_on_minute(now)):
            session = calendar.minute_to_session(now, direction="none")
            return datetime.now(timezone.utc), calendar.session_close(session).to_pydatetime()
    except Exception:
        pass

    if not wait_for_market:
        return None

    session = calendar.date_to_session(now.date(), direction="next")
    market_open = calendar.session_open(session).to_pydatetime()
    market_close = calendar.session_close(session).to_pydatetime()
    wait = (market_open - datetime.now(timezone.utc)).total_seconds()
    if wait < -60:
        session = calendar.next_session(session)
        market_open = calendar.session_open(session).to_pydatetime()
        market_close = calendar.session_close(session).to_pydatetime()
        wait = (market_open - datetime.now(timezone.utc)).total_seconds()
    if wait > max_wait_seconds:
        return None
    if wait > 0:
        print(f"Waiting {int(wait)}s for XNYS regular session...")
        time.sleep(wait)
    return datetime.now(timezone.utc), market_close


def _stage_ar(stage: str) -> str:
    return {
        "WATCH": "مراقبة",
        "BUILDING": "يتكوّن",
        "CONFIRMED": "مؤكد",
        "EXTENDED": "متأخر/ممتد",
        "FAILED": "فشل/انعكس",
    }.get(stage, stage)


def _price_ar(state: str) -> str:
    return {
        "LAGGING": "السعر لم يستجب بالكامل",
        "CONFIRMING": "السعر بدأ يؤكد",
        "EXTENDED": "السعر امتد؛ مطاردة العقد غير مفضلة",
        "DIVERGING": "السعر يتحرك عكس الفلو",
    }.get(state, state)


def _message(snapshot: ThesisSnapshot) -> str:
    bias_emoji = "🟢" if snapshot.bias == "BULLISH" else "🔴"
    bias_ar = "صاعد" if snapshot.bias == "BULLISH" else "هابط"
    actionable = "🟢 مؤهل للمراقبة اللحظية" if snapshot.actionable else "🟡 دليل رصدي — ليس أمر دخول"
    strikes = ", ".join(f"{value:g}" for value in snapshot.strikes[:6]) or "—"
    complex_line = (
        f"⚠️ مخاطرة Complex/Multi-leg: <b>{snapshot.complex_ratio:.0%}</b>"
        if snapshot.complex_parent_orders
        else "✅ لا توجد علامة Multi-leg مسيطرة في الدليل الحالي"
    )
    return "\n".join(
        [
            f"{bias_emoji} <b>BLACK BOX V9 — Thesis {html.escape(snapshot.underlying)} {bias_ar}</b>",
            f"الحالة: <b>{_stage_ar(snapshot.stage)}</b> | درجة الدليل: <b>{snapshot.evidence_grade}</b> <i>(ليست نسبة نجاح)</i>",
            "",
            f"💰 Premium مجمّع: <b>${snapshot.total_premium:,.0f}</b>",
            f"🧩 Parent Orders: <b>{snapshot.parent_orders}</b> | Realtime: <b>{snapshot.realtime_parent_orders}</b>",
            f"⚡ Sweeps موثقة: <b>{snapshot.sweep_parent_orders}</b> | ISO: <b>{snapshot.iso_parent_orders}</b>",
            f"🎯 Strikes مترابطة: <b>{strikes}</b>",
            "",
            f"📈 {_price_ar(snapshot.price_state)} | الحركة المتوافقة منذ أول فلو: <b>{snapshot.aligned_underlying_move_pct:+.2f}%</b>",
            f"⏱️ أحدث دليل منذ <b>{snapshot.freshest_age_seconds:.0f}s</b>",
            complex_line,
            "",
            f"<b>{actionable}</b>",
            "ℹ️ التجميع يعيد بناء Parent Orders بصورة محافظة، ويفصل الدليل اللحظي عن احتمالية النجاح. OI لا يثبت فتح مركز جديد حتى تسوية الجلسة التالية.",
        ]
    )


class ThesisPublisher:
    def __init__(self, state_path: Path, log_path: Path) -> None:
        self.state_path = state_path
        self.log_path = log_path
        loaded = _load(state_path, {})
        self.memory: dict[str, Any] = loaded if isinstance(loaded, dict) else {}
        self.records: dict[str, Any] = self.memory.setdefault("theses", {})
        self.latest: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()
        self.telegram_ready = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
        self.send_building = _bool_env("OPTIONS_REALTIME_SEND_BUILDING", False)

    def _should_publish(self, snapshot: ThesisSnapshot, previous: dict[str, Any]) -> bool:
        if snapshot.stage == "WATCH":
            return False
        if snapshot.stage == "BUILDING" and not self.send_building:
            return False
        if snapshot.stage in {"EXTENDED", "FAILED"} and not previous.get("message_id"):
            return False
        return (
            previous.get("stage") != snapshot.stage
            or previous.get("evidence_grade") != snapshot.evidence_grade
            or bool(previous.get("actionable")) != snapshot.actionable
        )

    def __call__(self, snapshot: ThesisSnapshot) -> None:
        with self.lock:
            data = snapshot.as_dict()
            self.latest[snapshot.thesis_id] = data
            previous = self.records.get(snapshot.thesis_id)
            previous = previous if isinstance(previous, dict) else {}
            if not self._should_publish(snapshot, previous):
                return

            message_id = previous.get("message_id")
            delivered = False
            error = ""
            if self.telegram_ready:
                try:
                    if message_id:
                        result = edit_html_message(int(message_id), _message(snapshot))
                        message_id = result.message_id or int(message_id)
                    else:
                        result = send_html_message(_message(snapshot), timeout=12)
                        message_id = result.message_id
                    delivered = True
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    print(f"Telegram thesis publish failed: {error}", file=sys.stderr)

            record = {
                "stage": snapshot.stage,
                "evidence_grade": snapshot.evidence_grade,
                "actionable": snapshot.actionable,
                "message_id": message_id,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "delivered": delivered,
                "last_error": error,
            }
            self.records[snapshot.thesis_id] = record
            _append_jsonl(
                self.log_path,
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "event": "thesis_transition",
                    "snapshot": data,
                    "delivery": record,
                },
            )
            self.flush()

    def flush(self, *, runtime: dict[str, Any] | None = None) -> None:
        with self.lock:
            self.memory["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.memory["architecture"] = "realtime_parent_order_thesis_v9"
            self.memory["latest"] = list(self.latest.values())
            if runtime is not None:
                self.memory["runtime"] = runtime
            _save(self.state_path, self.memory)


def _symbols(args_value: str) -> list[str]:
    raw = args_value or os.getenv("OPTIONS_REALTIME_SYMBOLS", "")
    values = [value.strip().upper() for value in raw.split(",") if value.strip()]
    return list(dict.fromkeys(values or DEFAULT_SYMBOLS))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BLACK BOX V9 realtime options parent-order + thesis intelligence"
    )
    parser.add_argument("--symbols", default="")
    parser.add_argument("--state", default="data/live/realtime_options_v9_state.json")
    parser.add_argument("--log", default="data/live/realtime_options_v9_transitions.jsonl")
    parser.add_argument("--wait-for-market", action="store_true")
    parser.add_argument("--until-market-close", action="store_true")
    parser.add_argument("--max-wait-seconds", type=int, default=5400)
    parser.add_argument("--max-runtime-seconds", type=int, default=17700)
    args = parser.parse_args()

    source = os.getenv("INTRINIO_OPTIONS_SOURCE", "realtime").strip().lower()
    if source != "realtime":
        raise RuntimeError(
            "BLACK BOX V9 hot path is fail-closed: INTRINIO_OPTIONS_SOURCE must be 'realtime'"
        )

    window = _market_window(
        wait_for_market=args.wait_for_market,
        max_wait_seconds=max(0, args.max_wait_seconds),
    )
    if window is None:
        print("Realtime worker skipped: XNYS regular session is not open and next open is outside wait window.")
        return
    started_at, market_close = window

    symbols = _symbols(args.symbols)
    publisher = ThesisPublisher(Path(args.state), Path(args.log))
    engine = RealtimeFlowEngine(
        thesis_window_seconds=int(os.getenv("OPTIONS_REALTIME_THESIS_WINDOW_SECONDS", "600")),
        max_event_age_seconds=int(os.getenv("OPTIONS_REALTIME_MAX_EVENT_AGE_SECONDS", "90")),
        min_confirmed_premium=float(os.getenv("OPTIONS_REALTIME_MIN_CONFIRMED_PREMIUM", "250000")),
        extended_move_pct=float(os.getenv("OPTIONS_REALTIME_EXTENDED_MOVE_PCT", "0.80")),
    )
    service = RealtimeFlowService(
        engine,
        on_snapshot=publisher,
        queue_size=int(os.getenv("OPTIONS_REALTIME_QUEUE_SIZE", "20000")),
    )
    config = IntrinioRealtimeConfig.from_env(symbols)
    if config.delayed:
        raise RuntimeError("Intrinio realtime adapter resolved delayed mode; refusing hot-path alerts")
    adapter = IntrinioRealtimeAdapter(service, config)

    stop_event = threading.Event()

    def stop_handler(signum: int, frame: Any) -> None:
        del signum, frame
        stop_event.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    adapter.start()
    print(
        "BLACK BOX V9 realtime started: "
        f"symbols={len(symbols)} provider={config.provider} market_close={market_close.isoformat()}"
    )

    runtime_deadline = started_at.timestamp() + max(60, args.max_runtime_seconds)
    if args.until_market_close:
        runtime_deadline = min(runtime_deadline, market_close.timestamp())

    try:
        while not stop_event.is_set() and time.time() < runtime_deadline:
            time.sleep(10)
            publisher.flush(
                runtime={
                    "started_at": started_at.isoformat(),
                    "market_close": market_close.isoformat(),
                    "symbols": symbols,
                    "adapter": adapter.stats(),
                }
            )
    finally:
        adapter.stop()
        publisher.flush(
            runtime={
                "started_at": started_at.isoformat(),
                "stopped_at": datetime.now(timezone.utc).isoformat(),
                "symbols": symbols,
                "adapter": adapter.stats(),
            }
        )
        print(f"BLACK BOX V9 realtime stopped: {adapter.stats()}")


if __name__ == "__main__":
    main()
