from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from options_radar.indicators import TechnicalSnapshot
from options_radar.journal import SignalJournal
from options_radar.market_clock import market_clock_state
from options_radar.scoring import score_chain
from options_radar.settings import Settings
from options_radar.stocks import StockRadar
from options_radar.storage import SignalStore


def technical(direction: str = "bullish") -> TechnicalSnapshot:
    bullish = direction == "bullish"
    return TechnicalSnapshot(
        symbol="TEST",
        close=100.0,
        ema9=99.0 if bullish else 101.0,
        ema21=98.0 if bullish else 102.0,
        ema50=95.0 if bullish else 104.0,
        ema200=90.0 if bullish else 108.0,
        rsi14=60.0 if bullish else 40.0,
        macd=2.0 if bullish else -2.0,
        macd_signal=1.0 if bullish else -1.0,
        atr14=4.0,
        realized_vol20=0.30,
        relative_volume20=1.8,
        resistance20=99.0 if bullish else 110.0,
        support20=90.0 if bullish else 101.0,
        direction=direction,
        catalyst="synthetic technical setup",
        catalyst_score=15.0,
        breakout=True,
    )


def chain(updated_at: datetime | None = None, option_type: str = "call") -> pd.DataFrame:
    updated_at = updated_at or datetime.now(timezone.utc)
    return pd.DataFrame(
        [
            {
                "contract_symbol": "TEST260821C00100000" if option_type == "call" else "TEST260821P00100000",
                "symbol": "TEST",
                "expiration": pd.Timestamp.now().normalize() + pd.Timedelta(days=30),
                "strike": 100.0,
                "option_type": option_type,
                "bid": 4.8,
                "ask": 5.2,
                "last": 5.0,
                "volume": 800,
                "open_interest": 1200,
                "iv": 0.35,
                "delta": 0.50 if option_type == "call" else -0.50,
                "gamma": 0.03,
                "theta": -0.04,
                "vega": 0.10,
                "underlying_price": 100.0,
                "updated_at": updated_at,
                "source": "unit-test",
                "data_quality": 0.90,
                "freshness_label": "test realtime",
                "aggressor_proxy": "ask",
            }
        ]
    )


def settings(tmp_path) -> Settings:
    return Settings(
        min_dte=14,
        max_dte=60,
        min_option_volume=10,
        min_open_interest=10,
        max_spread_pct=0.20,
        min_score=0,
        alert_score=0,
        alert_vol_oi=0.1,
        database_path=tmp_path / "alert_state.json",
        signal_journal_path=tmp_path / "signals.jsonl",
        outcome_path=tmp_path / "outcomes.json",
    )


def test_data_gate_rejects_very_stale_contract(tmp_path) -> None:
    stale = datetime.now(timezone.utc) - timedelta(days=8)
    result = score_chain(chain(stale), technical(), "risk_on", settings(tmp_path))
    assert result.empty


def test_dynamic_targets_follow_underlying_and_greeks(tmp_path) -> None:
    result = score_chain(chain(), technical(), "risk_on", settings(tmp_path))
    assert len(result) == 1
    row = result.iloc[0]
    assert row["target_1"] > row["entry_price"]
    assert row["target_2"] >= row["target_1"]
    assert row["stop_price"] < row["entry_price"]
    assert row["underlying_target_1"] > row["underlying_price"]
    assert row["underlying_invalidation"] < row["underlying_price"]
    assert row["reward_risk_1"] > 0
    assert row["data_status"] == "verified_by_source"


def test_bearish_stock_model_selects_put() -> None:
    history = pd.DataFrame(
        {
            "Close": [100.0] * 20,
            "Volume": [2_000_000] * 20,
        }
    )
    row = StockRadar._score(
        "TEST",
        technical("bearish"),
        history,
        "risk_off",
        {"score": -20, "category": "negative", "headline": "failed endpoint"},
    )
    assert row["setup_side"] == "put"
    assert row["target_1"] < row["price"]
    assert row["invalidation"] > row["price"]


def test_json_alert_store_persists_between_instances(tmp_path) -> None:
    path = tmp_path / "alert_state.json"
    first = SignalStore(path)
    first.mark_alerted("TEST-CONTRACT", 82.0, 2.5, "unit-test")
    second = SignalStore(path)
    assert second.was_alerted("TEST-CONTRACT") is True


def test_signal_journal_deduplicates_and_tracks_observed_prices(tmp_path, monkeypatch) -> None:
    journal = SignalJournal(
        tmp_path / "signals.jsonl",
        tmp_path / "outcomes.json",
        "test-model",
    )
    frame = score_chain(chain(), technical(), "risk_on", settings(tmp_path))
    now = datetime.now(timezone.utc)
    assert journal.record(frame, now) == 1
    assert journal.record(frame, now) == 0
    contract = str(frame.iloc[0]["contract_symbol"])
    monkeypatch.setattr(journal, "_fetch_quotes", lambda signals: {contract: 6.5})
    summary = journal.update_outcomes(now + timedelta(minutes=31))
    assert summary["tracked_signals"] == 1
    assert summary["priced_signals"] == 1
    assert summary["average_mfe_pct"] is not None


def test_market_clock_distinguishes_session_and_weekend() -> None:
    regular = market_clock_state(datetime(2026, 7, 21, 14, 0, tzinfo=timezone.utc))
    weekend = market_clock_state(datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc))
    assert regular.is_session is True
    assert regular.is_regular_open is True
    assert weekend.is_session is False
    assert weekend.is_regular_open is False
