"""Explosion Hunter public digest: compact, research-only, no price levels."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import publish_explosion_hunter as mod
from scripts.publish_explosion_hunter import SCHEMA, build_digest

NOW = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def _state():
    return {"generated_at": "2026-10-20T14:58:00+00:00", "symbols": {
        "AAA": {"stage": "IGNITION", "score": 81.234, "day_move_pct": 7.5, "rvol": 4.2,
                "float_shares": 8_500_000, "dollar_volume": 12_000_000, "price": 3.21,
                "official_catalyst_url": "https://www.sec.gov/Archives/edgar/data/1/x.htm",
                "catalyst_headline": "8-K material agreement", "dilution_risk": 60,
                "microcap_hunter": {"stage": "PRIORITY"}},
        "BBB": {"stage": "PRESSURE_BUILDING", "score": 64.0, "rvol": 2.1,
                "official_catalyst_url": "https://evil.example/sec.gov"},
        "CCC": {"stage": "EXTENDED", "score": 90.0, "day_move_pct": 55},
        "DDD": {"stage": "EXPLOSION", "score": 88.0},
        "EEE": {"stage": "WATCH", "score": 40.0},
        "FFF": {"stage": "NOT_A_STAGE", "score": 99.0},
    }}


def test_digest_orders_by_stage_drops_watch_and_never_publishes_prices():
    digest = build_digest(_state(), now=NOW)
    assert digest["schema"] == SCHEMA
    assert [r["symbol"] for r in digest["candidates"]] == ["DDD", "AAA", "BBB", "CCC"]
    assert digest["stage_counts"] == {"WATCH": 1, "PRESSURE_BUILDING": 1, "IGNITION": 1,
                                      "EXPLOSION": 1, "EXTENDED": 1}
    assert all("price" not in r for r in digest["candidates"])
    assert digest["price_levels_published"] is False
    assert digest["score_is_probability"] is False and digest["execution_authority"] is False
    assert digest["source_generated_at"] == "2026-10-20T14:58:00+00:00"


def test_only_https_sec_links_survive_and_fields_are_explicit():
    rows = {r["symbol"]: r for r in build_digest(_state(), now=NOW)["candidates"]}
    assert rows["AAA"]["official_catalyst_url"].startswith("https://www.sec.gov/")
    assert rows["BBB"]["official_catalyst_url"] is None
    assert rows["AAA"]["score"] == 81.2 and rows["AAA"]["microcap_stage"] == "PRIORITY"
    assert rows["BBB"]["float_shares"] is None  # missing stays missing


def test_naive_clock_rejected_and_main_never_fabricates(tmp_path: Path, monkeypatch):
    with pytest.raises(ValueError):
        build_digest(_state(), now=NOW.replace(tzinfo=None))
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["x", "--input", str(tmp_path / "missing.json"), "--output", str(out)])
    assert mod.main() == 0 and not out.exists()
