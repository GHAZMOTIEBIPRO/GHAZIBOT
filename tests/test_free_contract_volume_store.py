from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from options_radar.free_contract_volume_store import FreeContractVolumeStore
from options_radar.scanner import OptionsRadar
from options_radar.settings import Settings


def _chain(volume: float = 100, trade_time: str | None = "2026-10-05T19:30:00Z"):
    return pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "contract_symbol": "ABC261120C00100000",
                "volume": volume,
                "last_trade_timestamp": trade_time,
                "source": "yahoo/yfinance",
            }
        ]
    )


def test_store_requires_explicit_trade_timestamp_and_persists(tmp_path):
    path = tmp_path / "free_option_volume_history.json"
    store = FreeContractVolumeStore(path)

    missing = store.record_chain(
        _chain(trade_time=None),
        collected_at=datetime(2026, 10, 5, 20, 0, tzinfo=timezone.utc),
    )
    assert missing["recorded"] == 0
    assert missing["skipped_missing_trade_time"] == 1

    recorded = store.record_chain(
        _chain(volume=120),
        collected_at=datetime(2026, 10, 5, 20, 1, tzinfo=timezone.utc),
    )
    assert recorded["recorded"] == 1
    assert path.exists()

    restored = FreeContractVolumeStore(path)
    history = restored.history_frame("ABC261120C00100000")
    assert history["Volume"].tolist() == [120.0]
    assert history.iloc[0]["execution_grade"] == False  # noqa: E712


def test_same_session_uses_max_observed_cumulative_volume(tmp_path):
    store = FreeContractVolumeStore(tmp_path / "history.json")
    store.record_chain(_chain(volume=100))
    store.record_chain(_chain(volume=180))
    store.record_chain(_chain(volume=150))

    history = store.history_frame("ABC261120C00100000")
    assert len(history) == 1
    assert history.iloc[0]["Volume"] == 180.0


def test_store_keeps_distinct_market_sessions_from_trade_timestamps(tmp_path):
    store = FreeContractVolumeStore(tmp_path / "history.json")
    rows = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "contract_symbol": "ABC261120C00100000",
                "volume": 100,
                "last_trade_timestamp": "2026-10-02T19:30:00Z",
                "source": "yahoo/yfinance",
            },
            {
                "symbol": "ABC",
                "contract_symbol": "ABC261120C00100000",
                "volume": 125,
                "last_trade_timestamp": "2026-10-05T19:30:00Z",
                "source": "yahoo/yfinance",
            },
        ]
    )
    result = store.record_chain(rows)
    assert result["recorded"] == 2
    history = store.history_frame("ABC261120C00100000")
    assert history["Volume"].tolist() == [100.0, 125.0]
    assert [stamp.date().isoformat() for stamp in history.index] == [
        "2026-10-02",
        "2026-10-05",
    ]


def test_scanner_zero_key_history_loader_reads_local_store(tmp_path):
    settings = Settings(
        marketdata_token=None,
        tradier_token=None,
        free_option_volume_store_path=tmp_path / "history.json",
    )
    store = FreeContractVolumeStore(settings.free_option_volume_store_path)
    store.record_chain(
        pd.DataFrame(
            [
                {
                    "symbol": "ABC",
                    "contract_symbol": "ABC261120C00100000",
                    "volume": 90,
                    "last_trade_timestamp": "2026-09-30T19:30:00Z",
                    "source": "yahoo/yfinance",
                },
                {
                    "symbol": "ABC",
                    "contract_symbol": "ABC261120C00100000",
                    "volume": 110,
                    "last_trade_timestamp": "2026-10-01T19:30:00Z",
                    "source": "yahoo/yfinance",
                },
            ]
        )
    )

    radar = OptionsRadar.__new__(OptionsRadar)
    radar.settings = settings
    radar.free_volume_store = store
    result = radar._option_history_loader("ABC261120C00100000")

    assert result.source == "self_collected_free"
    assert result.metadata["zero_key"] is True
    assert result.metadata["execution_grade"] is False
    assert result.data["Volume"].tolist() == [90.0, 110.0]
