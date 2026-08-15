from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from options_radar.stream_overlay import (
    load_stream_snapshot,
    overlay_option_chain_from_stream,
)


CONTRACT = "XYZ260918C00100000"


def _chain() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contract_symbol": CONTRACT,
                "bid": 1.00,
                "ask": 1.10,
                "last": 1.05,
                "updated_at": "2026-08-14T14:00:00Z",
                "source": "tradier",
                "freshness_label": "brokerage feed",
                "data_quality": 0.90,
                "fabric_quote_provider": "tradier",
                "fabric_source_tier": "LIVE_OR_LICENSED",
            }
        ]
    )


def _snapshot(feed: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "generated_at": now,
        "option_feed": feed,
        "options": {
            CONTRACT: {
                "q": {"T": "q", "S": CONTRACT, "bp": 1.20, "ap": 1.30, "t": now},
                "t": {"T": "t", "S": CONTRACT, "p": 1.25, "s": 5, "t": now},
                "last_event_at": now,
            }
        },
    }


def test_indicative_stream_never_replaces_execution_quote():
    out, audit = overlay_option_chain_from_stream(_chain(), _snapshot("indicative"))
    row = out.iloc[0]
    assert row["bid"] == 1.00
    assert row["ask"] == 1.10
    assert row["last"] == 1.05
    assert row["stream_bid"] == 1.20
    assert row["stream_ask"] == 1.30
    assert bool(row["stream_execution_grade"]) is False
    assert audit["execution_quotes_replaced"] == 0


def test_fresh_opra_stream_replaces_execution_quote():
    out, audit = overlay_option_chain_from_stream(_chain(), _snapshot("opra"))
    row = out.iloc[0]
    assert row["bid"] == 1.20
    assert row["ask"] == 1.30
    assert row["last"] == 1.25
    assert row["fabric_quote_provider"] == "alpaca_opra_stream"
    assert row["fabric_source_tier"] == "LIVE_OR_LICENSED"
    assert row["data_quality"] >= 0.96
    assert audit["execution_quotes_replaced"] == 1


def test_stale_snapshot_is_rejected(tmp_path):
    payload = _snapshot("opra")
    payload["generated_at"] = (
        datetime.now(timezone.utc) - timedelta(minutes=5)
    ).isoformat()
    path = tmp_path / "stream.json"
    import json

    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_stream_snapshot(path, max_age_seconds=20) is None
