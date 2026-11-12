"""Stock analysis on the user's own uploaded daily bars.

Reuses the repository's tested computation unchanged: options_radar/daily_plan.py
computes, options_radar/analysis_card.py assembles the card and writes the fixed
Arabic template. Both are loaded by file path so the platform does not import the
options_radar package (whose __init__ pulls pandas and network providers).
"""
from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"ghazi_platform_{name}", ROOT / "options_radar" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


daily_plan = _load("daily_plan")
analysis_card = _load("analysis_card")


def last_closed_week_end(last_session: str) -> str:
    """A week counts only when its last session (Friday) is in the data."""
    d = date.fromisoformat(last_session)
    if d.weekday() >= 4:
        return last_session
    return (d - timedelta(days=d.weekday() + 1)).isoformat()


def analyse_user_bars(symbol: str, bars: list[dict[str, Any]], *, dataset_label: str) -> dict[str, Any]:
    last = bars[-1]["date"]
    provider = {"name": f"user_upload:{dataset_label}", "scope": "USER_PROVIDED_DAILY",
                "delay_note": "بيانات رفعها المستخدم؛ لا يتحقق النظام من مصدرها أو توقيتها.",
                "volume_scope": "as provided by the user"}
    plan = daily_plan.plan_for_symbol(symbol, bars, last_closed_session=last,
                                      last_closed_week_end=last_closed_week_end(last), provider=provider)
    card = analysis_card.build_card(plan, options_status="NOT_LICENSED_FOR_PLATFORM")
    text = analysis_card.explain_ar(card)
    supported, unsupported = analysis_card.numbers_supported(text, card) if card.get("available") else (True, [])
    return {"schema": "ghazi.platform.analysis.v1", "symbol": symbol, "card": card, "text_ar": text,
            "text_numbers_supported": supported, "unsupported_numbers": unsupported,
            "data_origin": "USER_PROVIDED", "visible_to": "owner_only",
            "probability": None, "execution_authority": False}
