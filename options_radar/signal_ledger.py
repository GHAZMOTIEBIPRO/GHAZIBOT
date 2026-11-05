"""Option signal ledger: identity, levels, paper monitor and public export.

One record per qualified contract signal, keyed by a stable ``signal_id`` so
Telegram, the site page ``/options/signal/{signal_id}`` and the outcome log all
point at the same object.

What this module decides, and what it deliberately does not:

- It does **not** create a bullish or bearish opinion and it does **not**
  approve a signal. Approval stays with ``options_radar/v11_gate.py``; a
  signal is CONFIRMED here only when the V11 decision attached to the row is
  approved *and* the quote at signal time is execution-grade (LIVE).
- Quote grading reuses ``execution_confidence.assess_execution_quote``; a
  source label alone never upgrades a quote.
- Paper entries fill on the **ask** and paper exits on the **bid**. A last
  trade price never fills anything.
- Observations older than the last processed quote, or older than the time
  the signal was published, are ignored (no hindsight, no retro targets).
- A bar whose bid range spans both the stop and a target cannot be ordered:
  the signal becomes AMBIGUOUS and is never counted as a win.
- Missing or stale quotes move the signal to DATA_STALE, which is neither a
  stop nor a target; the previous state resumes on the next fresh quote.

Standard library only, plus the sibling ``execution_confidence`` module.
"""
from __future__ import annotations

import hashlib
import html
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .execution_confidence import _parse_timestamp, assess_execution_quote

SCHEMA = "ghazi.signal_ledger.v1"
NY = ZoneInfo("America/New_York")
RIYADH = ZoneInfo("Asia/Riyadh")
SITE_URL = "https://ghazibot.vercel.app"

OCC_RE = re.compile(r"^(?P<root>[A-Z]{1,6})(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$")

# Quote grades (the "data status" shown on every surface).
LIVE = "LIVE"
DELAYED = "DELAYED"
RESEARCH_ONLY = "RESEARCH_ONLY"
STALE = "STALE"
UNAVAILABLE = "UNAVAILABLE"
GRADE_AR = {
    LIVE: "مباشرة وقابلة للتنفيذ",
    DELAYED: "متأخرة — للبحث فقط",
    RESEARCH_ONLY: "بحثية — غير معتمدة للتنفيذ",
    STALE: "قديمة",
    UNAVAILABLE: "غير متاحة",
}

# Decision states (entry decision) and monitor states (after publication).
WATCH, READY, CONFIRMED, NO_TRADE, INVALIDATED_DECISION = "WATCH", "READY", "CONFIRMED", "NO_TRADE", "INVALIDATED"
CREATED = "CREATED"
WATCHING = "WATCHING"
ENTRY_ELIGIBLE = "ENTRY_ELIGIBLE"
PAPER_ACTIVE = "PAPER_ACTIVE"
TARGET_1, TARGET_2, TARGET_3 = "TARGET_1", "TARGET_2", "TARGET_3"
STOPPED = "STOPPED"
INVALIDATED = "INVALIDATED"
EXPIRED = "EXPIRED"
DATA_STALE = "DATA_STALE"
AMBIGUOUS = "AMBIGUOUS"
CLOSED = "CLOSED"
TERMINAL = frozenset({TARGET_3, STOPPED, INVALIDATED, EXPIRED, AMBIGUOUS, CLOSED})
PRE_ENTRY = frozenset({CREATED, WATCHING, ENTRY_ELIGIBLE})
STATE_AR = {
    CREATED: "أُنشئت", WATCHING: "تحت المراقبة", ENTRY_ELIGIBLE: "السعر داخل منطقة الدخول (غير قابل للتنفيذ بعد)",
    PAPER_ACTIVE: "دخول ورقي مفعّل", TARGET_1: "تحقق الهدف الأول", TARGET_2: "تحقق الهدف الثاني",
    TARGET_3: "تحقق الهدف الثالث", STOPPED: "ضُرب وقف الخسارة", INVALIDATED: "أُلغيت الفرضية",
    EXPIRED: "انتهت الصلاحية", DATA_STALE: "البيانات متوقفة — لا وقف ولا هدف", AMBIGUOUS: "غامضة (الهدف والوقف في الشمعة نفسها)",
    CLOSED: "أُغلقت المتابعة",
}
TARGET_ORDER = (TARGET_1, TARGET_2, TARGET_3)
MAX_SERIES = 1500  # stamped quote observations kept per signal; the page builds candles from these


@dataclass(frozen=True)
class LedgerPolicy:
    """Risk policy defaults. They are explicit, versioned and not validated.

    They are not a calibrated edge; walk-forward evidence must justify any
    change. ``levels_method`` on every signal records which rule produced it.
    """

    version: str = "LEDGER_POLICY_V1"
    max_spread_pct: float = 10.0          # (ask - bid) / mid, percent
    max_chase_pct: float = 10.0           # max valid entry = ask_at_signal * (1 + x)
    stop_pct: float = 40.0                # premium stop below the entry reference
    target_r_multiples: tuple[float, float, float] = (1.0, 2.0, 3.0)
    min_reward_risk_t1: float = 0.8       # after spread and fees, measured on the bid
    slippage_pct: float = 1.0             # added to the paper ask fill
    fee_per_contract: float = 0.65        # USD per contract per side
    max_quote_age_seconds: float = 120.0  # same default as V11
    stale_after_seconds: float = 900.0    # monitor: no fresh quote for this long => DATA_STALE
    entry_window_minutes: float = 60.0    # signal expires if no entry inside this window
    last_trade_buffer_minutes: float = 30.0
    min_dte_minutes_for_0dte: float = 60.0


DEFAULT_POLICY = LedgerPolicy()


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso(stamp: datetime | None) -> str | None:
    return stamp.astimezone(timezone.utc).isoformat() if stamp else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


# ---------------------------------------------------------------- identity

def parse_occ(symbol: Any) -> dict[str, Any] | None:
    """Parse a compact OCC symbol (``AMD261030C00655000``). None when invalid."""
    text = str(symbol or "").strip().upper().replace(" ", "")
    match = OCC_RE.fullmatch(text)
    if not match:
        return None
    try:
        expiry = date(2000 + int(match["yy"]), int(match["mm"]), int(match["dd"]))
    except ValueError:
        return None
    strike = int(match["strike"]) / 1000.0
    if strike <= 0:
        return None
    return {"occ": text, "root": match["root"], "expiration": expiry.isoformat(),
            "side": "CALL" if match["cp"] == "C" else "PUT", "strike": strike}


def _previous_business_day(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def settlement_profile(root: str, expiration: str) -> dict[str, Any]:
    """Settlement style and last trading moment (New York) for the contract.

    Mirrors ``expiry_identity._product_defaults``. SPX (AM-settled) stops
    trading the business day before expiration; SPXW and equity/ETF options
    stop at 16:00 ET on expiration day. Exchange holidays and half days are
    not modelled here, so ``half_day_not_modelled`` is always reported.
    """
    expiry = date.fromisoformat(expiration)
    root = root.upper()
    if root == "SPX":
        style, kind, last_day = "AM", "CASH", _previous_business_day(expiry)
    elif root == "SPXW":
        style, kind, last_day = "PM", "CASH", expiry
    elif root in {"NDX", "XND", "NDXP"}:
        style, kind, last_day = ("PM" if root == "NDXP" else "UNKNOWN"), "CASH", expiry
    else:
        style, kind, last_day = "PM", "PHYSICAL", expiry
    last_trade = datetime.combine(last_day, time(16, 0), tzinfo=NY)
    return {"settlement": style, "settlement_kind": kind,
            "last_trade_at": _iso(last_trade), "half_day_not_modelled": True}


def ny_session(stamp: datetime) -> str:
    return stamp.astimezone(NY).date().isoformat()


def signal_id_for(occ: str, session: str, policy_version: str = DEFAULT_POLICY.version) -> str:
    """Stable id: one signal per contract per New York session and policy."""
    digest = hashlib.sha256(f"{occ}|{session}|{policy_version}".encode()).hexdigest()
    return digest[:16]


def signal_url(signal_id: str) -> str:
    return f"{SITE_URL}/options/signal/{signal_id}"


# ---------------------------------------------------------------- quote grade

def _two_sided(quote: dict[str, Any]) -> tuple[float, float] | None:
    bid, ask = _num(quote.get("bid")), _num(quote.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return bid, ask


def grade_quote(quote: dict[str, Any] | None, *, now: datetime,
                policy: LedgerPolicy = DEFAULT_POLICY) -> dict[str, Any]:
    """LIVE / DELAYED / RESEARCH_ONLY / STALE / UNAVAILABLE for one quote."""
    record = quote if isinstance(quote, dict) else {}
    sides = _two_sided(record)
    gate = assess_execution_quote(record, now=now, max_quote_age_seconds=policy.max_quote_age_seconds).as_dict()
    age = gate.get("quote_age_seconds")
    reasons = list(gate.get("blockers") or [])
    if sides is None:
        grade = UNAVAILABLE
        reasons.append("no_valid_two_sided_quote")
    elif not gate.get("quote_timestamp"):
        grade = UNAVAILABLE
        reasons.append("no_absolute_quote_timestamp")
    elif gate.get("execution_ready"):
        grade = LIVE
    elif age is not None and age > policy.stale_after_seconds:
        grade = STALE
    elif age is not None and age < -5.0:
        grade = UNAVAILABLE
        reasons.append("quote_timestamp_in_future")
    elif str(gate.get("source_mode") or "").upper().startswith("DELAYED"):
        grade = DELAYED
    else:
        grade = RESEARCH_ONLY
    return {"grade": grade, "label_ar": GRADE_AR[grade], "quote_timestamp": gate.get("quote_timestamp") or None,
            "quote_age_seconds": age, "source": record.get("source") or record.get("provider"),
            "execution_ready": grade == LIVE, "reasons": sorted({str(r) for r in reasons if r})}


# ---------------------------------------------------------------- levels

def compute_levels(ask: float, bid: float, policy: LedgerPolicy = DEFAULT_POLICY) -> dict[str, Any]:
    """Premium levels from the ask at signal time (R-multiple policy).

    Targets and the stop are compared with the **bid** by the monitor, so the
    spread is already a cost. Reward/risk to T1 is reported after fees and
    slippage, both measured per share.
    """
    entry = ask
    risk = entry * policy.stop_pct / 100.0
    stop = entry - risk
    targets = [entry + risk * r for r in policy.target_r_multiples]
    fill = ask * (1 + policy.slippage_pct / 100.0)
    fees = 2 * policy.fee_per_contract / 100.0
    reward_t1 = targets[0] - fill - fees
    loss = fill - stop + fees
    rr_t1 = reward_t1 / loss if loss > 0 else None
    return {
        "levels_method": f"R_MULTIPLE_{policy.version}",
        "entry_reference": _round(entry), "max_valid_entry": _round(ask * (1 + policy.max_chase_pct / 100.0)),
        "entry_zone": [_round(bid), _round(ask * (1 + policy.max_chase_pct / 100.0))],
        "stop": _round(stop), "targets": [_round(t) for t in targets],
        "paper_fill_assumption": _round(fill), "fees_per_share_round_trip": _round(fees, 5),
        "reward_risk_t1_after_costs": _round(rr_t1, 3),
        "exit_price_basis": "bid", "entry_price_basis": "ask",
    }


# ---------------------------------------------------------------- creation

def build_signal(candidate: dict[str, Any], *, now: datetime,
                 policy: LedgerPolicy = DEFAULT_POLICY) -> dict[str, Any]:
    """Turn one already-gated contract row into a signal record or a rejection.

    ``candidate`` is a row that went through ``apply_v11_gate`` (it carries
    ``v11_decision``). Returns ``{"accepted": bool, "signal": {...} | None,
    "rejections": [...]}``. Rejections are kept so alternative contracts can
    be explained.
    """
    row = dict(candidate or {})
    rejections: list[str] = []
    identity = parse_occ(row.get("contract_symbol") or row.get("occ") or row.get("symbol_occ"))
    if identity is None:
        return {"accepted": False, "signal": None, "rejections": ["invalid_occ_identity"]}
    side = str(row.get("side") or row.get("option_type") or "").upper()
    if side in {"C", "CALLS"}:
        side = "CALL"
    if side in {"P", "PUTS"}:
        side = "PUT"
    if side and side != identity["side"]:
        rejections.append("side_conflicts_with_occ")
    for key in ("strike", "expiration"):
        given = row.get(key)
        if given not in (None, ""):
            same = abs((_num(given) or -1) - identity["strike"]) < 1e-6 if key == "strike" \
                else str(given)[:10] == identity["expiration"]
            if not same:
                rejections.append(f"{key}_conflicts_with_occ")
    if row.get("adjusted") or row.get("non_standard"):
        rejections.append("adjusted_or_non_standard_contract")

    settlement = settlement_profile(identity["root"], identity["expiration"])
    last_trade = _parse_timestamp(settlement["last_trade_at"])
    if last_trade is None or now >= last_trade:
        rejections.append("contract_no_longer_trading")
    elif (last_trade - now) < timedelta(minutes=policy.min_dte_minutes_for_0dte):
        rejections.append("too_close_to_last_trade")

    quote = row.get("quote") if isinstance(row.get("quote"), dict) else row
    grade = grade_quote(quote, now=now, policy=policy)
    sides = _two_sided(quote)
    levels = None
    if sides is None:
        rejections.append("no_valid_two_sided_quote")
    else:
        bid, ask = sides
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid * 100 if mid > 0 else None
        if spread_pct is None or spread_pct > policy.max_spread_pct:
            rejections.append("spread_too_wide")
        levels = compute_levels(ask, bid, policy)
        levels["spread_pct"] = _round(spread_pct, 3)
        rr = levels.get("reward_risk_t1_after_costs")
        if rr is None or rr < policy.min_reward_risk_t1:
            rejections.append("reward_risk_below_policy")

    v11 = row.get("v11_decision") if isinstance(row.get("v11_decision"), dict) else {}
    approved = bool(v11.get("approved"))
    if not v11:
        rejections.append("v11_decision_missing")

    hard = [r for r in rejections if r not in {"reward_risk_below_policy", "spread_too_wide"}]
    if hard:
        return {"accepted": False, "signal": None, "rejections": sorted(set(rejections))}

    if approved and grade["grade"] == LIVE and not rejections:
        decision = CONFIRMED
    elif rejections:
        decision = NO_TRADE
    else:
        decision = WATCH
    if decision == NO_TRADE:
        return {"accepted": False, "signal": None, "rejections": sorted(set(rejections + list(v11.get("blockers") or [])))}

    session = ny_session(now)
    sid = signal_id_for(identity["occ"], session, policy.version)
    entry_deadline = min(now + timedelta(minutes=policy.entry_window_minutes),
                         last_trade - timedelta(minutes=policy.last_trade_buffer_minutes))
    reasons = [str(r) for r in (row.get("verified_reasons") or row.get("reasons") or []) if r][:3]
    signal = {
        "schema": SCHEMA, "signal_id": sid, "url": signal_url(sid), "policy_version": policy.version,
        "contract": {**identity, **settlement}, "underlying": str(row.get("underlying") or identity["root"]).upper(),
        "decision": decision, "evidence_grade": str(row.get("evidence_grade") or "") or None,
        "created_at": _iso(now), "session_ny": session, "signal_expires_at": _iso(entry_deadline),
        "underlying_price_at_signal": _num(row.get("underlying_price") or row.get("spot")),
        "underlying_price_source": row.get("underlying_price_source"),
        "invalidation": row.get("invalidation") if isinstance(row.get("invalidation"), dict) else None,
        "quote_at_signal": {"bid": sides[0], "ask": sides[1], "quote_timestamp": grade["quote_timestamp"],
                            "source": grade["source"], "grade": grade["grade"]},
        "data_grade": grade, "levels": levels, "reasons": reasons,
        "v11": {"approved": approved, "state": v11.get("state"), "blockers": list(v11.get("blockers") or [])},
        "telegram_eligible": decision == CONFIRMED and bool(row.get("telegram_eligible", approved)),
        "quote_series": [{"t": grade["quote_timestamp"], "bid": sides[0], "ask": sides[1], "grade": grade["grade"]}],
        "state": CREATED, "targets_hit": {}, "paper": None, "last_quote": None, "last_quote_at": None,
        "events": [], "telegram": {"message_id": None, "status": "NOT_SENT", "attempts": []},
        "outcome": None,
    }
    _event(signal, now, "CREATED", None, CREATED, reason="signal_created", quote=signal["quote_at_signal"])
    return {"accepted": True, "signal": signal, "rejections": sorted(set(rejections))}


# ---------------------------------------------------------------- monitor

def _event(signal: dict[str, Any], at: datetime, kind: str, src: str | None, dst: str | None, **extra: Any) -> None:
    events = signal.setdefault("events", [])
    events.append({"seq": len(events) + 1, "at": _iso(at), "type": kind, "from": src, "to": dst,
                   **{k: v for k, v in extra.items() if v is not None}})


def _transition(signal: dict[str, Any], at: datetime, new_state: str, *, reason: str,
                quote: dict[str, Any] | None = None) -> None:
    old = signal.get("state")
    if old == new_state:
        return
    signal["state"] = new_state
    _event(signal, at, "STATE", old, new_state, reason=reason, quote=quote)


def mark_published(signal: dict[str, Any], *, at: datetime, message_id: int | None) -> None:
    """Record that the alert reached Telegram (or the page). Monitoring starts here."""
    signal["published_at"] = _iso(at)
    tg = signal.setdefault("telegram", {})
    if message_id:
        tg["message_id"] = int(message_id)
        tg["status"] = "SENT"
    if signal.get("state") == CREATED:
        _transition(signal, at, WATCHING, reason="published")


def _close_paper(signal: dict[str, Any], exit_bid: float, at: datetime, reason: str) -> None:
    paper = signal.get("paper") or {}
    if not paper.get("fill"):
        return
    fill = float(paper["fill"])
    fees = float((signal.get("levels") or {}).get("fees_per_share_round_trip") or 0.0)
    risk = fill - float(signal["levels"]["stop"])
    pnl = exit_bid - fill - fees
    paper.update({"exit": _round(exit_bid), "exit_at": _iso(at), "exit_reason": reason,
                  "return_pct_after_costs": _round(pnl / fill * 100, 3),
                  "r_multiple": _round(pnl / risk, 3) if risk > 0 else None})
    signal["paper"] = paper


def observe(signal: dict[str, Any], observation: dict[str, Any], *, now: datetime,
            policy: LedgerPolicy = DEFAULT_POLICY) -> list[dict[str, Any]]:
    """Advance one signal with one quote observation. Returns new events.

    ``observation`` holds ``bid``, ``ask``, ``quote_timestamp``, ``source`` and
    optionally ``bid_low`` / ``bid_high`` (range inside a bar) and
    ``underlying_price``. Idempotent: replaying an observation changes nothing.
    """
    before = len(signal.get("events") or [])
    state = signal.get("state")
    if state in TERMINAL:
        return []
    published = _parse_timestamp(signal.get("published_at"))
    if published is None:
        return []  # nothing is monitored before the alert existed
    expires = _parse_timestamp(signal.get("signal_expires_at"))
    last_trade = _parse_timestamp((signal.get("contract") or {}).get("last_trade_at"))

    grade = grade_quote(observation, now=now, policy=policy)
    stamp = _parse_timestamp(grade.get("quote_timestamp"))
    last_seen = _parse_timestamp(signal.get("last_quote_at"))

    if last_trade is not None and now >= last_trade:
        _expire(signal, now)
        return signal["events"][before:]

    fresh = stamp is not None and grade["grade"] != UNAVAILABLE and \
        (grade["quote_age_seconds"] is not None and grade["quote_age_seconds"] <= policy.stale_after_seconds)
    if stamp is not None and (stamp <= published or (last_seen and stamp <= last_seen)):
        fresh = False  # replay, out-of-order, or before the alert: ignore entirely
        if state != DATA_STALE and last_seen and (now - last_seen).total_seconds() > policy.stale_after_seconds:
            _stale(signal, now, "no_new_quote")
        return signal["events"][before:]
    entered = state not in PRE_ENTRY and not (state == DATA_STALE and signal.get("resume_state") in PRE_ENTRY)
    if fresh and entered and grade["grade"] != LIVE:
        fresh = False  # exits are paper fills too: only execution-grade quotes may decide them
    if not fresh:
        if state != DATA_STALE:
            _stale(signal, now, grade["grade"].lower())
        return signal["events"][before:]

    sides = _two_sided(observation)
    bid, ask = sides  # fresh implies two-sided
    signal["last_quote"] = {"bid": bid, "ask": ask, "grade": grade["grade"], "source": grade["source"],
                            "quote_timestamp": grade["quote_timestamp"]}
    signal["last_quote_at"] = grade["quote_timestamp"]
    series = signal.setdefault("quote_series", [])
    series.append({"t": grade["quote_timestamp"], "bid": bid, "ask": ask, "grade": grade["grade"]})
    del series[:-MAX_SERIES]
    if state == DATA_STALE:
        state = signal.get("resume_state") or WATCHING
        _transition(signal, now, state, reason="data_resumed", quote=signal["last_quote"])

    levels = signal.get("levels") or {}
    stop, targets = float(levels["stop"]), [float(t) for t in levels["targets"]]
    invalidation = signal.get("invalidation") or {}
    under = _num(observation.get("underlying_price"))
    inv_level = _num(invalidation.get("underlying_level"))
    inv_hit = False
    if under is not None and inv_level is not None:
        inv_hit = under <= inv_level if signal["contract"]["side"] == "CALL" else under >= inv_level

    if state in PRE_ENTRY:
        if inv_hit:
            _transition(signal, now, INVALIDATED, reason="underlying_invalidation_before_entry", quote=signal["last_quote"])
        elif expires is not None and now >= expires:
            _transition(signal, now, EXPIRED, reason="entry_window_closed_without_entry", quote=signal["last_quote"])
            signal["outcome"] = "NOT_ENTERED"
        elif ask <= float(levels["max_valid_entry"]):
            if grade["grade"] == LIVE:
                fill = ask * (1 + policy.slippage_pct / 100.0)
                signal["paper"] = {"fill": _round(fill), "fill_at": grade["quote_timestamp"], "fill_basis": "ask+slippage",
                                   "fill_quote_source": grade["source"]}
                _transition(signal, now, PAPER_ACTIVE, reason="ask_inside_entry_zone_on_live_quote", quote=signal["last_quote"])
            elif state != ENTRY_ELIGIBLE:
                _transition(signal, now, ENTRY_ELIGIBLE, reason=f"ask_inside_zone_but_quote_{grade['grade'].lower()}",
                            quote=signal["last_quote"])
        elif state == ENTRY_ELIGIBLE:
            _transition(signal, now, WATCHING, reason="ask_left_entry_zone", quote=signal["last_quote"])
        return signal["events"][before:]

    # After entry: compare targets and stop with the bid (and the bid range if given).
    low = _num(observation.get("bid_low"))
    high = _num(observation.get("bid_high"))
    low = min(bid, low) if low is not None else bid
    high = max(bid, high) if high is not None else bid
    stop_touched = low <= stop
    reached = [i for i, t in enumerate(targets) if high >= t and TARGET_ORDER[i] not in signal["targets_hit"]]
    if stop_touched and reached and (low != high):
        _transition(signal, now, AMBIGUOUS, reason="stop_and_target_inside_same_bar", quote=signal["last_quote"])
        signal["outcome"] = "AMBIGUOUS"
        return signal["events"][before:]
    for i in reached:
        signal["targets_hit"][TARGET_ORDER[i]] = {"at": grade["quote_timestamp"], "bid": bid, "level": targets[i]}
        _transition(signal, now, TARGET_ORDER[i], reason=f"bid_reached_t{i + 1}", quote=signal["last_quote"])
    if signal["state"] == TARGET_3:
        _close_paper(signal, targets[2], now, "target_3")
        signal["outcome"] = "TARGET_3"
        return signal["events"][before:]
    if stop_touched:
        _close_paper(signal, min(bid, stop), now, "stop")
        _transition(signal, now, STOPPED, reason="bid_reached_stop", quote=signal["last_quote"])
        signal["outcome"] = "STOPPED_AFTER_" + max(signal["targets_hit"], default="ENTRY")
    elif inv_hit:
        _close_paper(signal, bid, now, "invalidation")
        _transition(signal, now, CLOSED, reason="underlying_invalidation_after_entry", quote=signal["last_quote"])
        signal["outcome"] = "CLOSED_ON_INVALIDATION"
    return signal["events"][before:]


def _stale(signal: dict[str, Any], now: datetime, reason: str) -> None:
    state = signal.get("state")
    if state in TERMINAL or state == DATA_STALE:
        return
    signal["resume_state"] = state
    _transition(signal, now, DATA_STALE, reason=f"data_stale:{reason}")


def _expire(signal: dict[str, Any], now: datetime) -> None:
    state = signal.get("state")
    resume = signal.get("resume_state") if state == DATA_STALE else state
    _transition(signal, now, EXPIRED, reason="contract_last_trade_time_passed")
    if resume in PRE_ENTRY:
        signal["outcome"] = "NOT_ENTERED"
    elif signal.get("paper") and not signal["paper"].get("exit"):
        signal["outcome"] = "EXPIRED_OPEN_UNRESOLVED"  # no valid exit quote is assumed
    else:
        signal["outcome"] = signal.get("outcome") or "EXPIRED"


def sweep(signal: dict[str, Any], *, now: datetime, policy: LedgerPolicy = DEFAULT_POLICY) -> list[dict[str, Any]]:
    """Time-only checks when no observation arrived this cycle."""
    before = len(signal.get("events") or [])
    if signal.get("state") in TERMINAL or not signal.get("published_at"):
        return []
    last_trade = _parse_timestamp((signal.get("contract") or {}).get("last_trade_at"))
    if last_trade is not None and now >= last_trade:
        _expire(signal, now)
        return signal["events"][before:]
    expires = _parse_timestamp(signal.get("signal_expires_at"))
    state = signal.get("state")
    if expires and now >= expires and (state in PRE_ENTRY or
                                       (state == DATA_STALE and signal.get("resume_state") in PRE_ENTRY)):
        _transition(signal, now, EXPIRED, reason="entry_window_closed_without_entry")
        signal["outcome"] = "NOT_ENTERED"
        return signal["events"][before:]
    seen = _parse_timestamp(signal.get("last_quote_at")) or _parse_timestamp(signal.get("published_at"))
    if seen and (now - seen).total_seconds() > policy.stale_after_seconds:
        _stale(signal, now, "no_new_quote")
    return signal["events"][before:]


# ---------------------------------------------------------------- ledger state

def empty_ledger() -> dict[str, Any]:
    return {"schema": SCHEMA, "updated_at": None, "signals": {}}


def upsert(ledger: dict[str, Any], signal: dict[str, Any]) -> bool:
    """Insert a new signal; never overwrite an existing id (idempotent)."""
    signals = ledger.setdefault("signals", {})
    if signal["signal_id"] in signals:
        return False
    signals[signal["signal_id"]] = signal
    return True


def summarize(ledger: dict[str, Any]) -> dict[str, Any]:
    """Counts kept apart: direction, entry, targets and paper P&L are different questions."""
    rows = list((ledger.get("signals") or {}).values())
    closed = [r for r in rows if (r.get("paper") or {}).get("return_pct_after_costs") is not None]
    rets = sorted(float(r["paper"]["return_pct_after_costs"]) for r in closed)
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else None
    by_state: dict[str, int] = {}
    for r in rows:
        by_state[r.get("state") or "UNKNOWN"] = by_state.get(r.get("state") or "UNKNOWN", 0) + 1
    return {
        "total": len(rows), "by_state": by_state,
        "entered": sum(1 for r in rows if r.get("paper")),
        "not_entered": sum(1 for r in rows if r.get("outcome") == "NOT_ENTERED"),
        "ambiguous": sum(1 for r in rows if r.get("state") == AMBIGUOUS),
        "t1_hit": sum(1 for r in rows if TARGET_1 in (r.get("targets_hit") or {})),
        "t2_hit": sum(1 for r in rows if TARGET_2 in (r.get("targets_hit") or {})),
        "t3_hit": sum(1 for r in rows if TARGET_3 in (r.get("targets_hit") or {})),
        "paper_closed": len(closed),
        "paper_median_return_pct": _round(rets[len(rets) // 2], 3) if rets else None,
        "paper_profit_factor": _round(pf, 3),
        "win_rate_pct": None,
        "win_rate_policy": "لا تُعرض نسبة نجاح قبل اكتمال العينة الناضجة والمعايرة خارج العينة.",
    }


# ---------------------------------------------------------------- public export

_PRICE_KEYS = ("quote_at_signal", "last_quote", "levels", "paper", "underlying_price_at_signal", "targets_hit",
               "quote_series")


def public_view(signal: dict[str, Any], *, display_permitted: bool) -> dict[str, Any]:
    """What the site may show. Prices and price-derived levels are withheld
    unless the quote source has a recorded public-display right."""
    out = {k: v for k, v in signal.items() if k not in ("telegram",)}
    out["telegram"] = {"status": (signal.get("telegram") or {}).get("status")}
    if not display_permitted:
        for key in _PRICE_KEYS:
            if key in out:
                out[key] = {"status": "LICENSE_BLOCKED"} if out[key] is not None else None
        out["events"] = [{k: v for k, v in e.items() if k != "quote"} for e in signal.get("events") or []]
        out["display"] = {"prices": "LICENSE_BLOCKED",
                          "note_ar": "أسعار العقد ومستوياته محجوبة لعدم ثبوت حق النشر العام لمصدرها."}
    else:
        out["display"] = {"prices": "PERMITTED"}
    return out


def display_permitted(source: Any, *, closed_families: list[str], family_of: Any,
                      display_sources: tuple[str, ...]) -> bool:
    """Fail closed: a source must be on the owner's recorded public-display
    allowlist *and* outside every closed family. Unknown sources are blocked."""
    text = str(source or "").strip().lower()
    if not text or family_of(text, closed_families) is not None:
        return False
    return any(token and token.lower() in text for token in display_sources)


def build_public_ledger(ledger: dict[str, Any], *, now: datetime, closed_families: list[str],
                        family_of: Any, display_sources: tuple[str, ...] = (), limit: int = 200) -> dict[str, Any]:
    rows = sorted((ledger.get("signals") or {}).values(), key=lambda r: r.get("created_at") or "", reverse=True)[:limit]
    published = []
    for row in rows:
        source = (row.get("quote_at_signal") or {}).get("source")
        permitted = display_permitted(source, closed_families=closed_families, family_of=family_of,
                                      display_sources=display_sources)
        published.append(public_view(row, display_permitted=permitted))
    return {"schema": SCHEMA + ".public", "generated_at": _iso(now), "decision_authority": False,
            "research_only": True, "summary": summarize(ledger), "signals": published,
            "policy_ar": ("الدخول الورقي على سعر الطلب Ask والخروج على سعر العرض Bid. لا تُحتسب أهداف قبل وقت "
                          "نشر التوصية، والشمعة التي تحوي الهدف والوقف معًا تُسجَّل غامضة ولا تُحسب ربحًا.")}


# ---------------------------------------------------------------- Telegram text

def _fmt(value: Any) -> str:
    number = _num(value)
    return "—" if number is None else f"{number:,.2f}"


def _ny(value: Any) -> str:
    stamp = _parse_timestamp(value)
    if not stamp:
        return "—"
    ny = stamp.astimezone(NY)
    return f"{ny:%Y-%m-%d %H:%M} نيويورك ({stamp.astimezone(RIYADH):%H:%M} الرياض)"


def telegram_text(signal: dict[str, Any]) -> str:
    """Arabic alert text over computed facts (fixed template, HTML-escaped)."""
    e = html.escape
    c = signal["contract"]
    q = signal.get("quote_at_signal") or {}
    lv = signal.get("levels") or {}
    t = list(lv.get("targets") or [None, None, None])
    reasons = signal.get("reasons") or []
    inv = signal.get("invalidation") or {}
    lines = [
        "<b>GHAZI RADAR Ω | توصية خيارات</b>", "",
        f"الشركة: <b>{e(signal['underlying'])}</b>",
        f"الاتجاه: <b>{e(c['side'])}</b>",
        f"الحالة: <b>{e(signal['decision'])}</b> — {e(STATE_AR.get(signal.get('state'), signal.get('state') or ''))}",
        f"العقد: <code>{e(c['occ'])}</code>",
        f"Strike: {_fmt(c['strike'])}",
        f"الانتهاء: {e(c['expiration'])} (تسوية {e(c['settlement'])})",
        f"وقت الإشارة: {e(_ny(signal['created_at']))}",
        f"سعر الأصل الأساسي: {_fmt(signal.get('underlying_price_at_signal'))}",
        "", "سعر العقد:", f"Bid: {_fmt(q.get('bid'))}", f"Ask: {_fmt(q.get('ask'))}", "",
        f"منطقة الدخول: {_fmt((lv.get('entry_zone') or [None, None])[0])} – {_fmt(lv.get('max_valid_entry'))}",
        f"الهدف الأول: {_fmt(t[0])}", f"الهدف الثاني: {_fmt(t[1])}", f"الهدف الثالث: {_fmt(t[2])}",
        f"وقف الخسارة: {_fmt(lv.get('stop'))}",
        f"العائد إلى المخاطرة (للهدف الأول بعد التكاليف): {_fmt(lv.get('reward_risk_t1_after_costs'))}",
        "", "أهم أسباب التوصية:",
    ]
    lines += [f"• {e(r)}" for r in reasons] or ["• —"]
    lines += ["", "شروط إلغاء التوصية:",
              f"• {e(str(inv.get('text_ar') or 'كسر مستوى الإلغاء للأصل أو انتهاء نافذة الدخول'))}",
              f"• نافذة الدخول تنتهي: {e(_ny(signal.get('signal_expires_at')))}", "",
              f"جودة الأدلة: {e(signal.get('evidence_grade') or '—')}",
              f"جودة البيانات: {e(GRADE_AR.get(q.get('grade'), '—'))} — {e(str(q.get('source') or '—'))}",
              "", "الأسعار مقارنة: الدخول على Ask والأهداف والوقف على Bid. ليست أمر تداول.",
              f'<a href="{e(signal["url"])}">عرض شارت العقد ومتابعة الأهداف</a>']
    history = [ev for ev in signal.get("events") or [] if ev.get("type") == "STATE" and ev.get("to") != WATCHING]
    if history:
        lines += ["", "<b>سجل المتابعة:</b>"]
        lines += [f"• {e(_ny(ev['at']))}: {e(STATE_AR.get(ev['to'], ev['to']))}" for ev in history[-8:]]
    return "\n".join(lines)


def update_text(signal: dict[str, Any], event: dict[str, Any]) -> str:
    """Short reply for a notable state change (targets, stop, invalidation, stale)."""
    e = html.escape
    to = event.get("to")
    basis = "على سعر العرض Bid" if to in (TARGET_1, TARGET_2, TARGET_3, STOPPED) else ""
    return "\n".join([
        f"<b>GHAZI RADAR Ω | تحديث</b> <code>{e(signal['contract']['occ'])}</code>",
        f"{e(STATE_AR.get(to, to or ''))} {basis}".strip(),
        f"الوقت: {e(_ny(event.get('at')))}",
        f'<a href="{e(signal["url"])}">الشارت والسجل</a>',
    ])


NOTIFY_STATES = frozenset({PAPER_ACTIVE, TARGET_1, TARGET_2, TARGET_3, STOPPED, INVALIDATED, AMBIGUOUS, DATA_STALE, CLOSED})
