from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from options_radar.halt_news_engine import NewsEvent, collect_fast_news
from scripts.telegram_transport import edit_html_message, send_html_message

RIYADH = ZoneInfo("Asia/Riyadh")
STATE_SCHEMA = "news_flash_24x7_v1"

_POSITIVE_TERMS: dict[str, int] = {
    "fda approval": 5,
    "fda approves": 5,
    "approved by the fda": 5,
    "positive topline": 5,
    "positive top-line": 5,
    "met its primary endpoint": 5,
    "met the primary endpoint": 5,
    "raises guidance": 4,
    "raised guidance": 4,
    "record revenue": 3,
    "record sales": 3,
    "contract award": 4,
    "awarded contract": 4,
    "wins contract": 4,
    "strategic partnership": 3,
    "share repurchase": 3,
    "stock repurchase": 3,
    "buyback": 3,
    "breakthrough therapy": 4,
    "clinical hold lifted": 5,
    "patent granted": 2,
    "special dividend": 3,
}

_NEGATIVE_TERMS: dict[str, int] = {
    "registered direct offering": 5,
    "public offering": 4,
    "at-the-market offering": 5,
    "atm offering": 5,
    "bankruptcy": 5,
    "delisting": 5,
    "going concern": 4,
    "reverse stock split": 4,
    "clinical hold": 5,
    "failed to meet": 5,
    "did not meet the primary endpoint": 5,
    "lowers guidance": 4,
    "lowered guidance": 4,
    "cuts guidance": 4,
    "investigation": 3,
    "convertible notes": 3,
    "convertible financing": 3,
}

_MATERIAL_TERMS: dict[str, int] = {
    "earnings": 2,
    "financial results": 2,
    "quarterly results": 2,
    "revenue": 2,
    "eps": 2,
    "guidance": 3,
    "merger": 4,
    "acquisition": 4,
    "to acquire": 4,
    "tender offer": 4,
    "strategic partnership": 3,
    "collaboration agreement": 3,
    "license agreement": 3,
    "contract": 2,
    "fda": 4,
    "clinical trial": 3,
    "phase 3": 3,
    "phase iii": 3,
    "phase 2": 2,
    "phase ii": 2,
    "primary endpoint": 4,
    "offering": 4,
    "financing": 3,
    "bankruptcy": 5,
    "delisting": 5,
    "buyback": 3,
    "repurchase": 3,
    "dividend": 2,
    "patent": 2,
    "chief executive officer": 2,
    "ceo": 2,
    "resigns": 2,
    "resignation": 2,
}

_DIRECT_PROVIDERS = {
    "globenewswire_rss",
    "businesswire_rss",
    "prnewswire_google_rss",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    events = payload.get("events")
    if not isinstance(events, dict):
        events = {}
    return {"schema": STATE_SCHEMA, "events": events}


def _save(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_published(value: str, *, now: datetime | None = None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    current = now or datetime.now(timezone.utc)
    candidates: list[datetime] = []
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        candidates.append(parsed)
    except ValueError:
        pass
    try:
        candidates.append(parsedate_to_datetime(text))
    except (TypeError, ValueError, OverflowError):
        pass
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y-%m-%d %H:%M:%S"):
        try:
            candidates.append(datetime.strptime(text, fmt))
        except ValueError:
            pass
    for parsed in candidates:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        # Reject pathological timestamps rather than making stale news look new.
        if parsed.year >= 2000 and parsed <= current.replace(microsecond=999999):
            return parsed
    return None


def event_fingerprint(event: NewsEvent) -> str:
    raw = "|".join(
        (
            str(event.symbol or "").upper().strip(),
            str(event.provider or "").lower().strip(),
            str(event.url or "").strip(),
            str(event.headline or "").lower().strip()[:320],
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def classify_materiality(event: NewsEvent) -> tuple[str, int, list[str]]:
    text = str(event.headline or "").lower()
    positive = [(term, weight) for term, weight in _POSITIVE_TERMS.items() if term in text]
    negative = [(term, weight) for term, weight in _NEGATIVE_TERMS.items() if term in text]
    generic = [(term, weight) for term, weight in _MATERIAL_TERMS.items() if term in text]

    pos_score = max((weight for _, weight in positive), default=0)
    neg_score = max((weight for _, weight in negative), default=0)
    generic_score = max((weight for _, weight in generic), default=0)
    materiality = max(pos_score, neg_score, generic_score)

    sentiment = _number(event.sentiment)
    if pos_score > neg_score:
        bias = "POSITIVE"
    elif neg_score > pos_score:
        bias = "NEGATIVE"
    elif sentiment >= 0.18:
        bias = "POSITIVE"
    elif sentiment <= -0.18:
        bias = "NEGATIVE"
    else:
        bias = "NEUTRAL"

    reasons = [term for term, _ in sorted(positive + negative + generic, key=lambda row: row[1], reverse=True)]
    reasons = list(dict.fromkeys(reasons))[:4]
    if materiality == 0 and abs(sentiment) >= 0.35 and _number(event.relevance) >= 0.7:
        materiality = 1
    return bias, materiality, reasons


def source_class(event: NewsEvent) -> str:
    return "DIRECT_COMPANY_RELEASE" if event.provider in _DIRECT_PROVIDERS else "SECONDARY_NEWS"


def _normalise_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    output = frame.copy()
    if isinstance(output.columns, pd.MultiIndex):
        return output
    output.columns = [str(column).title() for column in output.columns]
    if "Close" not in output.columns:
        return pd.DataFrame()
    index = pd.to_datetime(output.index, errors="coerce")
    valid = ~index.isna()
    output = output.loc[valid].copy()
    index = index[valid]
    if getattr(index, "tz", None) is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    output.index = index
    return output.sort_index()


def extract_symbol_frame(download: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if download is None or download.empty:
        return pd.DataFrame()
    symbol = str(symbol).upper().strip()
    if not isinstance(download.columns, pd.MultiIndex):
        return _normalise_frame(download)

    levels = [set(map(str, download.columns.get_level_values(level))) for level in range(download.columns.nlevels)]
    frame: pd.DataFrame | None = None
    if symbol in levels[0]:
        frame = download[symbol]
    elif len(levels) > 1 and symbol in levels[1]:
        frame = download.xs(symbol, axis=1, level=1)
    return _normalise_frame(frame)


def download_price_frames(symbols: list[str]) -> dict[str, pd.DataFrame]:
    unique = list(dict.fromkeys(str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()))[:12]
    if not unique:
        return {}
    try:
        downloaded = yf.download(
            tickers=" ".join(unique),
            period="2d",
            interval="1m",
            prepost=True,
            auto_adjust=False,
            progress=False,
            group_by="ticker",
            threads=True,
            timeout=15,
        )
    except Exception as exc:
        print(f"News flash price batch degraded: {type(exc).__name__}: {exc}")
        return {}
    return {symbol: extract_symbol_frame(downloaded, symbol) for symbol in unique}


def price_reaction(frame: pd.DataFrame | None, event_at: datetime, bias: str) -> dict[str, float] | None:
    data = _normalise_frame(frame)
    if data.empty or "Close" not in data:
        return None
    event_at = event_at.astimezone(timezone.utc)
    before = data[data.index < pd.Timestamp(event_at)]
    after = data[data.index >= pd.Timestamp(event_at)]
    if before.empty or after.empty:
        return None

    baseline = _number(pd.to_numeric(before["Close"], errors="coerce").dropna().iloc[-1], math.nan)
    closes = pd.to_numeric(after["Close"], errors="coerce").dropna()
    if not math.isfinite(baseline) or baseline <= 0 or closes.empty:
        return None
    current = _number(closes.iloc[-1], math.nan)
    highs = pd.to_numeric(after.get("High", after["Close"]), errors="coerce").dropna()
    lows = pd.to_numeric(after.get("Low", after["Close"]), errors="coerce").dropna()
    if not math.isfinite(current) or highs.empty or lows.empty:
        return None

    signed_move = ((current / baseline) - 1.0) * 100.0
    high_move = ((float(highs.max()) / baseline) - 1.0) * 100.0
    low_move = ((float(lows.min()) / baseline) - 1.0) * 100.0
    if bias == "POSITIVE":
        aligned = signed_move
        peak_aligned = max(0.0, high_move)
    elif bias == "NEGATIVE":
        aligned = -signed_move
        peak_aligned = max(0.0, -low_move)
    else:
        aligned = abs(signed_move)
        peak_aligned = max(abs(high_move), abs(low_move))

    fade = 0.0
    if peak_aligned >= 0.5:
        fade = max(0.0, min(100.0, ((peak_aligned - max(0.0, aligned)) / peak_aligned) * 100.0))
    return {
        "baseline": round(baseline, 4),
        "current": round(current, 4),
        "signed_move_pct": round(signed_move, 3),
        "aligned_move_pct": round(aligned, 3),
        "peak_aligned_pct": round(peak_aligned, 3),
        "fade_pct": round(fade, 2),
        "post_high": round(float(highs.max()), 4),
        "post_low": round(float(lows.min()), 4),
    }


def reaction_state(reaction: dict[str, float] | None, *, bias: str, age_minutes: float) -> str:
    if not reaction:
        return "UNPRICED"
    signed = _number(reaction.get("signed_move_pct"))
    aligned = _number(reaction.get("aligned_move_pct"))
    peak = _number(reaction.get("peak_aligned_pct"))
    fade = _number(reaction.get("fade_pct"))

    if bias == "POSITIVE" and signed <= -1.0:
        return "DIVERGING"
    if bias == "NEGATIVE" and signed >= 1.0:
        return "DIVERGING"
    if peak >= 3.0 and fade >= 50.0 and aligned <= peak * 0.65:
        return "FADED"
    if aligned >= 8.0 or (peak >= 10.0 and fade < 30.0):
        return "EXTENDED"
    if aligned >= 1.0:
        return "EARLY" if age_minutes <= 20.0 and aligned < 4.0 else "RUNNING"
    return "NO_REACTION"


def _status_ar(status: str) -> tuple[str, str]:
    return {
        "EARLY": ("🟢", "مبكر — الحركة ما زالت في بدايتها"),
        "RUNNING": ("🟢", "الحركة جارية — راقب الجودة ولا تطارد"),
        "EXTENDED": ("🟠", "ممتد — لا تطارد السعر بعد الخبر"),
        "FADED": ("🟡", "تراجع بعد اندفاعة — انتظر إعادة تمركز"),
        "DIVERGING": ("🔴", "السعر يتحرك عكس اتجاه الخبر"),
        "NO_REACTION": ("⚪️", "لم تظهر استجابة سعرية واضحة بعد"),
        "UNPRICED": ("⚪️", "لا توجد شموع دقيقة صالحة بعد الخبر حتى الآن"),
    }.get(status, ("⚪️", status))


def _action_ar(status: str) -> str:
    return {
        "EARLY": "الفائدة: دخل الخبر مبكرًا. راقب تأكيد 5m/15m والفوليوم قبل أي قرار.",
        "RUNNING": "الفائدة: الحركة بدأت. لا تدخل لمجرد الخبر؛ انتظر تثبيت/إعادة اختبار بدل اللحاق.",
        "EXTENDED": "لا مطاردة: جزء كبير من الحركة حصل. الأفضل انتظار قاعدة جديدة أو سحب منظم ثم تأكيد جديد.",
        "FADED": "هذا يفسر حالة: الخبر قوي لكن السهم صار نازل بعد ارتفاع. لا تطارد؛ انتظر Higher Low أو استعادة VWAP/قمة 5m مع فوليوم.",
        "DIVERGING": "الخبر وحده غير كافٍ؛ حركة السعر لا تؤيده الآن.",
        "NO_REACTION": "الخبر وصل قبل الحركة الواضحة؛ ضعه تحت المراقبة وانتظر الشارت والفوليوم.",
        "UNPRICED": "وصل الخبر قبل وجود تسعير قابل للقياس؛ سيُعاد فحص نفس الرسالة لاحقًا.",
    }.get(status, "راقب الشارت والفوليوم قبل القرار.")


def format_message(record: dict[str, Any]) -> str:
    bias = str(record.get("bias") or "NEUTRAL")
    bias_icon = "🟢" if bias == "POSITIVE" else "🔴" if bias == "NEGATIVE" else "🟡"
    bias_ar = "إيجابي" if bias == "POSITIVE" else "سلبي" if bias == "NEGATIVE" else "محايد/غير محسوم"
    status = str(record.get("reaction_state") or "UNPRICED")
    status_icon, status_text = _status_ar(status)
    published = parse_published(str(record.get("published") or ""))
    published_text = published.astimezone(RIYADH).strftime("%Y-%m-%d %H:%M") if published else "غير متاح"
    age = _number(record.get("age_minutes"))

    lines = [
        f"⚡ <b>BLACK BOX NEWS FLASH | {html.escape(str(record.get('symbol') or ''))}</b>",
        f"{bias_icon} الخبر: <b>{bias_ar}</b> | {status_icon} <b>{html.escape(status_text)}</b>",
        f"📰 {html.escape(str(record.get('headline') or '')[:520])}",
        f"⏱ النشر: {published_text} بتوقيت الرياض | العمر: {age:.0f}د",
        f"📡 {html.escape(str(record.get('source') or '')[:120])} | {html.escape(str(record.get('source_class') or ''))}",
    ]
    reaction = record.get("reaction")
    if isinstance(reaction, dict):
        lines.append(
            "💵 قبل الخبر "
            f"{_number(reaction.get('baseline')):.2f} → الآن {_number(reaction.get('current')):.2f} "
            f"({ _number(reaction.get('signed_move_pct')):+.2f}%)"
        )
        lines.append(
            f"📈 أقصى حركة مع اتجاه الخبر: {_number(reaction.get('peak_aligned_pct')):.2f}%"
            f" | تراجع عن أفضل حركة: {_number(reaction.get('fade_pct')):.0f}%"
        )
    reasons = record.get("material_reasons")
    if isinstance(reasons, list) and reasons:
        lines.append("🧩 سبب الأهمية: " + "، ".join(html.escape(str(item)) for item in reasons[:3]))
    lines.append(f"🧭 <b>{html.escape(_action_ar(status))}</b>")
    url = str(record.get("url") or "").strip()
    if url.startswith("https://"):
        lines.append(f'<a href="{html.escape(url, quote=True)}">فتح الخبر</a>')
    lines.append("<i>Flash سريع للمعلومة وحركة السعر؛ ليس إثباتًا رسميًا ولا أمر شراء/بيع.</i>")
    return "\n".join(lines)


def should_edit(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if str(previous.get("reaction_state")) != str(current.get("reaction_state")):
        return True
    old = previous.get("reaction") if isinstance(previous.get("reaction"), dict) else {}
    new = current.get("reaction") if isinstance(current.get("reaction"), dict) else {}
    if not old and new:
        return True
    if old and new:
        if abs(_number(new.get("signed_move_pct")) - _number(old.get("signed_move_pct"))) >= 2.0:
            return True
        if abs(_number(new.get("fade_pct")) - _number(old.get("fade_pct"))) >= 25.0:
            return True
    return False


def _record_from_event(
    event: NewsEvent,
    *,
    published: datetime,
    now: datetime,
    frame: pd.DataFrame | None,
) -> dict[str, Any]:
    bias, materiality, reasons = classify_materiality(event)
    age_minutes = max(0.0, (now - published).total_seconds() / 60.0)
    reaction = price_reaction(frame, published, bias)
    status = reaction_state(reaction, bias=bias, age_minutes=age_minutes)
    return {
        "symbol": str(event.symbol or "").upper().strip(),
        "headline": str(event.headline or "").strip(),
        "source": str(event.source or "").strip(),
        "provider": str(event.provider or "").strip(),
        "url": str(event.url or "").strip(),
        "published": published.isoformat(),
        "bias": bias,
        "materiality": materiality,
        "material_reasons": reasons,
        "source_class": source_class(event),
        "age_minutes": round(age_minutes, 2),
        "reaction": reaction,
        "reaction_state": status,
    }


def _event_from_record(record: dict[str, Any]) -> NewsEvent:
    return NewsEvent(
        symbol=str(record.get("symbol") or ""),
        headline=str(record.get("headline") or ""),
        source=str(record.get("source") or ""),
        url=str(record.get("url") or ""),
        published=str(record.get("published") or ""),
        relevance=1.0,
        sentiment=0.0,
        provider=str(record.get("provider") or ""),
    )


def run(
    *,
    state_path: Path,
    max_age_minutes: int,
    update_window_minutes: int,
    max_new_alerts: int,
) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    state = _load(state_path)
    registry: dict[str, Any] = state["events"]

    events = collect_fast_news(known_symbols=None)
    fresh: list[tuple[datetime, int, NewsEvent]] = []
    for event in events:
        published = parse_published(event.published, now=now)
        if published is None:
            continue
        age_minutes = (now - published).total_seconds() / 60.0
        if age_minutes < -2 or age_minutes > max_age_minutes:
            continue
        _, materiality, _ = classify_materiality(event)
        if materiality < 2:
            continue
        fresh.append((published, materiality, event))
    fresh.sort(key=lambda row: (row[0], row[1]), reverse=True)

    active_records: list[tuple[str, dict[str, Any], datetime]] = []
    for fp, record in list(registry.items()):
        if not isinstance(record, dict):
            registry.pop(fp, None)
            continue
        published = parse_published(str(record.get("published") or ""), now=now)
        if published is None:
            continue
        age = (now - published).total_seconds() / 60.0
        if 0 <= age <= update_window_minutes and record.get("message_id"):
            active_records.append((fp, record, published))

    fresh_symbols = [event.symbol for _, _, event in fresh if event_fingerprint(event) not in registry]
    active_symbols = [record.get("symbol") for _, record, _ in active_records]
    frames = download_price_frames([*fresh_symbols[:max_new_alerts], *active_symbols])

    sent = 0
    edited = 0
    new_fingerprints: set[str] = set()
    for published, _, event in fresh:
        if sent >= max_new_alerts:
            break
        fp = event_fingerprint(event)
        if fp in registry:
            continue
        record = _record_from_event(
            event,
            published=published,
            now=now,
            frame=frames.get(str(event.symbol).upper()),
        )
        result = send_html_message(format_message(record))
        record["message_id"] = result.message_id
        record["sent_at"] = now.isoformat()
        registry[fp] = record
        new_fingerprints.add(fp)
        sent += 1

    for fp, old_record, published in active_records[:10]:
        if fp in new_fingerprints:
            continue
        event = _event_from_record(old_record)
        current = _record_from_event(
            event,
            published=published,
            now=now,
            frame=frames.get(str(event.symbol).upper()),
        )
        current["message_id"] = old_record.get("message_id")
        current["sent_at"] = old_record.get("sent_at")
        if not should_edit(old_record, current):
            continue
        message_id = int(old_record.get("message_id") or 0)
        if message_id <= 0:
            continue
        edit_html_message(message_id, format_message(current))
        current["updated_at"] = now.isoformat()
        registry[fp] = current
        edited += 1

    # Keep the dedupe registry bounded while retaining enough history to avoid
    # replaying older feed items after a temporary provider outage.
    cutoff = now.timestamp() - (72 * 3600)
    for fp, record in list(registry.items()):
        published = parse_published(str(record.get("published") or ""), now=now) if isinstance(record, dict) else None
        if published and published.timestamp() < cutoff:
            registry.pop(fp, None)

    state["schema"] = STATE_SCHEMA
    state["events"] = registry
    _save(state_path, state)
    return {"discovered": len(events), "fresh_material": len(fresh), "sent": sent, "edited": edited}


def main() -> None:
    parser = argparse.ArgumentParser(description="24x7 keyless company-news flash with post-news price reaction tracking")
    parser.add_argument("--state", default="data/live/news_flash_24x7.json")
    parser.add_argument("--max-age-minutes", type=int, default=int(os.getenv("NEWS_FLASH_MAX_AGE_MINUTES", "60")))
    parser.add_argument("--update-window-minutes", type=int, default=int(os.getenv("NEWS_FLASH_UPDATE_WINDOW_MINUTES", "240")))
    parser.add_argument("--max-new-alerts", type=int, default=int(os.getenv("NEWS_FLASH_MAX_NEW_ALERTS", "5")))
    args = parser.parse_args()

    stats = run(
        state_path=Path(args.state),
        max_age_minutes=max(10, min(args.max_age_minutes, 180)),
        update_window_minutes=max(30, min(args.update_window_minutes, 480)),
        max_new_alerts=max(1, min(args.max_new_alerts, 8)),
    )
    print(
        "News Flash 24x7: "
        + " ".join(f"{key}={value}" for key, value in stats.items())
    )


if __name__ == "__main__":
    main()
