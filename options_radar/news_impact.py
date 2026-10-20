"""Documented HIGH / MEDIUM / LOW impact rules for public news items.

Impact is a triage label for how much attention an item deserves, never a
direction, a probability or a price prediction. Rules, applied in order:

R1 Source cap: an unofficial or unauthenticated source (news search RSS,
   GDELT, press-wire copy not verified as the issuer's release) can reach at
   most MEDIUM, whatever the headline says.
R2 Official macro: a scheduled or released CPI, Employment Situation (NFP),
   PPI or FOMC statement / rate decision is HIGH; FOMC minutes, GDP, retail
   sales, JOLTS and the Employment Cost Index are MEDIUM; other official
   macro items are LOW.
R3 Issuer events: headlines naming a high-potency event (FDA decision, trial
   result, definitive merger / acquisition / tender offer, offering / ATM /
   registered direct, bankruptcy, delisting, going-concern doubt, guidance
   change) start at HIGH; earnings or financial results start at MEDIUM;
   other corporate mentions start at LOW. R1 then caps unofficial items.
   Unofficial opinion / analysis / preview pieces ("undervalued", "should
   you buy", "what to expect", questions, price targets) are LOW.
R4 Age: items older than 72 hours drop one level (HIGH -> MEDIUM -> LOW).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

LEVELS = ("LOW", "MEDIUM", "HIGH")
STALE_AFTER = timedelta(hours=72)

_HIGH_ISSUER = re.compile(
    r"\b(FDA|approv\w*|complete response letter|CRL|clinical hold|phase [1-3]\w* (?:data|results)|"
    r"topline|trial (?:met|failed|results)|definitive (?:merger|agreement)|to acquire|acquisition of|"
    r"tender offer|merger|public offering|registered direct|at[- ]the[- ]market|ATM offering|"
    r"bankruptcy|chapter 11|delist\w*|going concern|guidance (?:cut|raise\w*|lower\w*)|"
    r"(?:cuts|raises|lowers) (?:its )?(?:full[- ]year )?(?:guidance|outlook))\b",
    re.IGNORECASE,
)
_MEDIUM_ISSUER = re.compile(
    r"\b(earnings|quarterly results|(?:first|second|third|fourth)[- ]quarter|Q[1-4] (?:results|revenue)|"
    r"revenue|EPS|results)\b",
    re.IGNORECASE,
)
_OPINION = re.compile(
    r"(undervalued|overvalued|value opportunity|should you|is it time|what to expect|could be|"
    r"\bbuy\b|\bsell\b|stocks? to (?:watch|buy)|prediction|forecast|price target|\?|"
    r"motley fool|zacks|seeking alpha)",
    re.IGNORECASE,
)
_HIGH_MACRO = re.compile(
    r"\b(consumer price index|CPI|employment situation|nonfarm|producer price index|PPI|"
    r"FOMC statement|federal open market committee statement|"
    r"(?:raises|lowers|maintains|holds) (?:the )?(?:target range|federal funds rate))\b",
    re.IGNORECASE,
)
_MEDIUM_MACRO = re.compile(
    r"\b(minutes of the federal open market committee|FOMC minutes|gross domestic product|GDP|"
    r"retail sales|job openings|JOLTS|employment cost index)\b",
    re.IGNORECASE,
)
_OFFICIAL_AUTHORITIES = {"OFFICIAL_SCHEDULE", "OFFICIAL_PUBLICATION", "OFFICIAL_SEC_FILING"}


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _lower(level: str) -> str:
    return LEVELS[max(0, LEVELS.index(level) - 1)]


def classify(item: dict[str, Any], *, now: datetime, macro: bool = False) -> dict[str, Any]:
    text = str(item.get("headline") or item.get("title") or "")
    official = (str(item.get("authority") or "") in _OFFICIAL_AUTHORITIES
                or item.get("official_sec_filing") is True
                or item.get("issuer_release_authenticated") is True)
    rules: list[str] = []
    if macro:
        level = "HIGH" if _HIGH_MACRO.search(text) else "MEDIUM" if _MEDIUM_MACRO.search(text) else "LOW"
        rules.append("R2_OFFICIAL_MACRO_" + level)
    elif not official and _OPINION.search(text):
        level = "LOW"
        rules.append("R3_OPINION_OR_ANALYSIS_LOW")
    else:
        level = "HIGH" if _HIGH_ISSUER.search(text) else "MEDIUM" if _MEDIUM_ISSUER.search(text) else "LOW"
        rules.append("R3_ISSUER_EVENT_" + level)
    if not official and level == "HIGH":
        level = "MEDIUM"
        rules.append("R1_UNOFFICIAL_SOURCE_CAP")
    stamp = _parse(item.get("published_at"))
    if stamp is not None and now - stamp > STALE_AFTER and level != "LOW":
        level = _lower(level)
        rules.append("R4_OLDER_THAN_72H")
    return {"impact_level": level, "impact_rules": rules}


def annotate(payload: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Add impact_level / impact_rules to every item in the public lists."""
    for key, macro in (("google_news_attention", False), ("press_wire_attention", False),
                       ("gdelt_attention", False), ("fed_monetary", True), ("bls_upcoming", True)):
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                item.update(classify(item, now=now, macro=macro))
    payload["impact_policy"] = {
        "version": "NEWS_IMPACT_RULES_V1",
        "levels": list(LEVELS),
        "impact_is_direction": False,
        "impact_is_probability": False,
        "unofficial_max_level": "MEDIUM",
        "stale_after_hours": int(STALE_AFTER.total_seconds() // 3600),
    }
    return payload
