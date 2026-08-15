from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from options_radar.stream_gateway import (
    SnapshotStore,
    configured_stream_symbols,
    watchdog_restart_reason,
)


def test_stream_gateway_dedupes_and_caps_symbols(monkeypatch):
    stocks = ",".join([f"S{index}" for index in range(40)] + ["S1"])
    options = ",".join([f"OPT{index}" for index in range(230)] + ["OPT1"])
    monkeypatch.setenv("STREAM_STOCK_SYMBOLS", stocks)
    monkeypatch.setenv("STREAM_OPTION_CONTRACTS", options)
    stock_symbols, option_contracts = configured_stream_symbols()
    assert len(stock_symbols) == 30
    assert len(option_contracts) == 200
    assert len(stock_symbols) == len(set(stock_symbols))
    assert len(option_contracts) == len(set(option_contracts))


def test_watchdog_only_restarts_active_stale_streams():
    assert (
        watchdog_restart_reason(
            market_active=False,
            connected_age_seconds=300,
            event_age_seconds=120,
            grace_seconds=60,
            stale_seconds=45,
        )
        is None
    )
    assert (
        watchdog_restart_reason(
            market_active=True,
            connected_age_seconds=30,
            event_age_seconds=None,
            grace_seconds=60,
            stale_seconds=45,
        )
        is None
    )
    assert (
        watchdog_restart_reason(
            market_active=True,
            connected_age_seconds=70,
            event_age_seconds=None,
            grace_seconds=60,
            stale_seconds=45,
        )
        == "no_events_after_connect_grace"
    )
    reason = watchdog_restart_reason(
        market_active=True,
        connected_age_seconds=120,
        event_age_seconds=50,
        grace_seconds=60,
        stale_seconds=45,
    )
    assert reason is not None and reason.startswith("stream_event_stale_")


def test_snapshot_store_records_source_lag_gap_and_reconnect_metrics(tmp_path, monkeypatch):
    monotonic_now = [100.0]
    monkeypatch.setattr(
        "options_radar.stream_gateway.time.monotonic",
        lambda: monotonic_now[0],
    )
    path = tmp_path / "stream.json"
    store = SnapshotStore(
        path,
        "iex",
        "indicative",
        flush_interval_seconds=999,
        gap_warn_seconds=5,
    )
    store.mark_connecting("stock")

    event_time = datetime.now(timezone.utc) - timedelta(seconds=2)
    store.update(
        "stock",
        {"S": "SPY", "T": "q", "t": event_time.isoformat(), "bp": 100, "ap": 101},
    )
    monotonic_now[0] = 107.5
    store.update(
        "stock",
        {
            "S": "SPY",
            "T": "q",
            "t": datetime.now(timezone.utc).isoformat(),
            "bp": 100.5,
            "ap": 101.5,
        },
    )
    store.record_reconnect("stock", "transport reset")
    store.record_reconnect("stock", "stale", watchdog=True)
    store.flush(force=True)

    payload = json.loads(path.read_text(encoding="utf-8"))
    health = payload["health"]["streams"]["stock"]
    assert payload["schema_version"] == 2
    assert health["events"] == 2
    assert health["max_transport_gap_seconds"] >= 7.0
    assert health["gaps_over_warn"] == 1
    assert health["max_event_lag_ms"] >= 1000
    assert health["reconnect_attempts"] == 1
    assert health["watchdog_restarts"] == 1
