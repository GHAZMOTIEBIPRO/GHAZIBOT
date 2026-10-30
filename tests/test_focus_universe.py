"""The user's named U.S. index and company options watchlist has first priority."""
from options_radar.focus_universe import (
    FOCUS_INDICES, FOCUS_STOCKS, FOCUS_OPTIONABLE,
    INDEX_OPTION_ROOTS, SECONDARY_STOCKS,
)
from options_radar.optionable_universe import IndependentOptionableUniverse
from options_radar.index_direction import DIRECTION_SYMBOLS
from scripts.build_index_context import FIVE_MIN_SYMBOLS
from scripts.build_stock_watch_charts import LARGE_WATCH, WATCH, FIVE_MIN
from scripts.run_classical_direction_radar import DEFAULT_COMPANIES, _symbols_from_env


def test_requested_indices_have_separate_index_pipeline():
    assert FOCUS_INDICES == ("SPX", "NDX", "SPY", "QQQ")
    assert set(FOCUS_INDICES) <= set(DIRECTION_SYMBOLS)
    assert set(FOCUS_INDICES) <= set(FIVE_MIN_SYMBOLS)
    assert INDEX_OPTION_ROOTS["SPX"] == ("SPX", "SPXW")
    assert INDEX_OPTION_ROOTS["NDX"] == ("NDX", "NDXP")
    assert "SPX" not in FOCUS_OPTIONABLE and "NDX" not in FOCUS_OPTIONABLE


def test_stock_focus_is_deduplicated_and_visible_in_chart_and_classical_paths(monkeypatch):
    assert len(FOCUS_STOCKS) == len(set(FOCUS_STOCKS)) == 9
    assert len(FOCUS_OPTIONABLE) == len(set(FOCUS_OPTIONABLE))
    assert set(FOCUS_STOCKS) <= set(DEFAULT_COMPANIES[:48])
    assert set(FOCUS_STOCKS) <= set(LARGE_WATCH)
    assert set(FOCUS_STOCKS) <= set(WATCH)
    assert set(FOCUS_STOCKS) <= set(FIVE_MIN)
    assert "GOOG" in FOCUS_STOCKS and "GOOGL" in FOCUS_STOCKS
    assert "BABA" in FOCUS_STOCKS
    assert set(SECONDARY_STOCKS) <= set(DEFAULT_COMPANIES)
    monkeypatch.delenv("CLASSICAL_DIRECTION_SYMBOLS", raising=False)
    assert _symbols_from_env()[:len(FOCUS_STOCKS)] == list(FOCUS_STOCKS)


def test_option_builder_focus_precedes_attention_but_never_overrides_official(monkeypatch):
    builder = IndependentOptionableUniverse()
    monkeypatch.setattr(builder, "fetch_official", lambda: (
        ["AAPL", "NVDA", "SPY", "QQQ", "BABA", "GOOG", "GOOGL", "META"],
        [], ["EU"], {}, False))
    monkeypatch.setattr(builder, "fetch_cboe_attention", lambda limit=100: (
        ["AAPL", "NVDA"], [], None))
    result = builder.build(
        ["AAPL", "NVDA", "SPY", "QQQ"],
        max_symbols=10,
        focus_symbols=("SPY", "QQQ", "BABA", "GOOG", "GOOGL", "META", "TSLA"),
    )
    assert result.official_verified is True
    assert result.symbols[:6] == ["SPY", "QQQ", "BABA", "GOOG", "GOOGL", "META"]
    assert "TSLA" not in result.symbols  # Not in verified OCC fixture.
    assert result.symbols[6:8] == ["AAPL", "NVDA"]


def test_focus_only_prioritizes_discovery_without_claiming_official_proof(monkeypatch):
    builder = IndependentOptionableUniverse()
    monkeypatch.setattr(builder, "fetch_official", lambda: ([], [], [], {}, False))
    monkeypatch.setattr(builder, "fetch_cboe_attention", lambda limit=100: ([], [], None))
    result = builder.build(
        ["AAPL"], include_cboe_attention=False, max_symbols=10,
        focus_symbols=("SPY", "QQQ", "BABA"),
    )
    assert result.symbols[:3] == ["SPY", "QQQ", "BABA"]
    assert result.official_verified is False
    assert any("focus only prioritizes" in note.lower() for note in result.limitations)


def test_configured_universe_contains_focus_without_duplicate_entries():
    from pathlib import Path
    values = [
        line.strip() for line in Path("data/universe.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert values[:2] == ["SPY", "QQQ"]
    assert values[2:2+len(FOCUS_STOCKS)] == list(FOCUS_STOCKS)
    assert len(values) == len(set(values))
