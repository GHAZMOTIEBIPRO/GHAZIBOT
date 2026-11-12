"""Commercial data-rights gate for everything the platform shows.

A signed-in platform, even on a free plan, is a commercial service. A value from
the research artifacts may therefore be shown only if its provider's record in
`data/source_rights.json` has BOTH:

- `commercial_use_on_free_tier` = VERIFIED, and
- `public_display_raw` (raw values) or `public_display_derived` (derived values)
  = VERIFIED.

UNKNOWN fails closed exactly like RESTRICTED. A provider missing from the matrix
is UNKNOWN. When the text of an item is not cleared, the item is reduced to its
public identity — symbol, date, the source's name and the official https link —
so the user can read it at the source; the platform does not republish it.

Before this gate runs, the existing publication guard (options_radar/public_guard)
removes anything whose source names a closed family, so both layers apply.
"""
from __future__ import annotations

import importlib.util
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Source strings seen in artifacts -> provider key in data/source_rights.json.
SOURCE_ALIASES: dict[str, tuple[str, ...]] = {
    "sec_edgar": ("sec edgar", "sec.gov", "edgar", "8-k", "10-q", "10-k", "form 4"),
    "openfda": ("openfda", "open.fda", "fda.gov"),
    "federal_register": ("federal register", "federalregister.gov"),
    "usaspending": ("usaspending",),
    "treasury_fiscaldata": ("fiscaldata", "treasury"),
    "federal_reserve": ("federalreserve.gov", "federal reserve"),
    "nyfed_reference_rates": ("newyorkfed", "ny fed", "sofr", "effr"),
    "ofr_stfm": ("ofr", "financialresearch.gov"),
    "dol_eta539": ("dol", "eta 539", "oui.doleta"),
    "cftc": ("cftc",),
    "gdelt": ("gdelt",),
    "bea": ("bea.gov", "bea "),
    "census": ("census",),
    "alpaca": ("alpaca",),
    "yahoo": ("yahoo", "yfinance", "yahooquery"),
    "nasdaq_web": ("nasdaq.com", "api.nasdaq.com"),
    "cboe_delayed": ("cboe",),
    "google_news_rss": ("news.google", "google news"),
    "prnewswire": ("prnewswire",),
    "globenewswire": ("globenewswire",),
    "businesswire": ("businesswire",),
    "company_ir_feeds": ("investor relations", "ir feed"),
    "tradingview_widgets": ("tradingview",),
}


@lru_cache(maxsize=4)
def _matrix(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("providers") or {}
    except (OSError, ValueError):
        return {}


def provider_for(source: Any) -> str | None:
    text = str(source or "").strip().lower()
    if not text:
        return None
    for key, tokens in SOURCE_ALIASES.items():
        if any(tok in text for tok in tokens):
            return key
    return None


def status(provider: str | None, right: str, *, rights_path: Path) -> str:
    if not provider:
        return "UNKNOWN"
    entry = _matrix(str(rights_path)).get(provider) or {}
    return str(((entry.get("rights") or {}).get(right) or {}).get("status") or "UNKNOWN")


def commercial_display(provider: str | None, *, derived: bool, rights_path: Path) -> dict[str, Any]:
    """Decision for showing one provider's values inside the paid platform."""
    display_right = "public_display_derived" if derived else "public_display_raw"
    commercial = status(provider, "commercial_use_on_free_tier", rights_path=rights_path)
    display = status(provider, display_right, rights_path=rights_path)
    allowed = commercial == "VERIFIED" and display == "VERIFIED"
    return {"provider": provider or "unlisted", "allowed": allowed,
            "commercial_use": commercial, display_right: display,
            "reason_ar": None if allowed else
            f"حق العرض التجاري للمصدر ({provider or 'غير مدرج في مصفوفة الحقوق'}) غير موثق: "
            f"الاستخدام التجاري {commercial}، العرض {display}."}


def official_link(value: Any) -> str | None:
    url = str(value or "").strip()
    return url if url.startswith("https://") and len(url) < 500 else None


def _load_public_guard():
    spec = importlib.util.spec_from_file_location(
        "ghazi_platform_public_guard", ROOT / "options_radar" / "public_guard.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_GUARD = None


def guarded(payload: Any, *, kind: str) -> Any:
    """Run the repository's publication guard on an artifact before any use."""
    global _GUARD
    if _GUARD is None:
        _GUARD = _load_public_guard()
    if isinstance(payload, dict):
        family = _GUARD._tagged_family(payload, _GUARD.closed_families())
        if family:
            # The whole artifact comes from a closed family (guard_payload would drop it
            # to None): keep only our own production time and the published reason.
            return {"status": payload.get("status") or "LICENSE_BLOCKED", "generated_at": payload.get("generated_at"),
                    "reason_ar": payload.get("reason_ar") or "مصدر الملف عائلة مغلقة الحقوق؛ حُجب كاملًا.",
                    "enable_with": payload.get("enable_with"), "license_blocked_family": family, "redacted": True}
    return _GUARD.guard_payload(payload, kind=kind)
