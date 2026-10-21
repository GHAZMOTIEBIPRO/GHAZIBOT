"""Alpaca Basic IEX authorized internal research: no data publication or false alerts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from options_radar.vcp_minervini_shadow import vcp_trend_shadow
from scripts.alpaca_vcp_private import (
    ENDPOINT,
    SCHEMA,
    authorization,
    fetch_daily_bars,
    private_message,
    run,
    sanitize_daily_bars,
)

NOW = datetime(2026, 10, 22, 16, 0, tzinfo=timezone.utc)


def sample_bars():
    dates = pd.bdate_range(end="2026-10-21", periods=95, tz="America/New_York")
    rows = []
    for index, stamp in enumerate(dates):
        close = 12.0 + 0.03 * index
        band = 0.42 if index < 77 else 0.10
        vol = 1100 if index < 85 else 120
        rows.append({
            "t": stamp.tz_convert(timezone.utc).isoformat(),
            "o": close - 0.02, "h": close + band,
            "l": close - band, "c": close, "v": vol,
        })
    return rows


class FakeResponse:
    def __init__(self, content: dict | None = None, *, bad: bool = False):
        self.content = content or {"bars": sample_bars(), "next_page_token": None}
        self.bad = bad

    def raise_for_status(self):
        if self.bad:
            raise requests.HTTPError("Not authorized")

    def json(self):
        return self.content


class Client:
    def __init__(self, response: FakeResponse | None = None):
        self.calls = []
        self.response = response or FakeResponse()

    def get(self, url, *, params, headers, timeout):
        self.calls.append((url, dict(params), dict(headers), timeout))
        assert url.startswith(ENDPOINT)
        assert headers["APCA-API-KEY-ID"] == "not-a-secret"
        assert headers["APCA-API-SECRET-KEY"] == "fake"
        assert params["feed"] == "iex"
        assert params["timeframe"] == "1Day"
        assert params["adjustment"] == "raw"
        assert timeout <= 15
        return self.response


ENABLED = {"ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
           "ALPACA_API_KEY": "not-a-secret", "ALPACA_SECRET_KEY": "fake"}


def test_no_credentials_or_attestation_sends_no_network_request():
    assert authorization(ENABLED) == "AUTHORIZED_INTERNAL_ONLY"
    for env in ({}, {"ALPACA_API_KEY": "not-a-secret", "ALPACA_SECRET_KEY": "fake"},
                {"ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true"}):
        client = Client()
        out, state = run(now=NOW, env=env, client=client)
        assert out["status"] != "INTERNAL_RESEARCH"
        assert out["raw_market_data_published"] is False
        assert out["tickers_published"] is False
        assert out["execution_authority"] is False
        assert out["requested_symbols"] == 0
        assert not client.calls and state == {}


def test_candle_validation_and_iex_provenance():
    clean = sanitize_daily_bars(sample_bars(), now=NOW)
    assert len(clean) == 95 and clean.index.tz is not None
    result = vcp_trend_shadow(clean, source_family="alpaca_iex")
    assert result["stage"] == "TIGHT_WATCH"
    assert result["source_family"] == "alpaca_iex"
    assert result["source_last_daily_bar"] == "2026-10-21"
    assert result["independent_confirmation"] is False
    assert result["option_execution_eligible"] is False
    with pytest.raises(ValueError):
        vcp_trend_shadow(clean, source_family="unlicensed")


def test_source_day_is_rejected_if_incomplete_or_stale_or_unsorted():
    same_day = {**sample_bars()[-1], "t": "2026-10-22T04:00:00+00:00"}
    series = sample_bars() + [same_day]
    assert len(sanitize_daily_bars(series, now=NOW)) == 95
    assert sanitize_daily_bars(sample_bars(), now=NOW+timedelta(days=8)).empty
    broken = sample_bars()
    broken[-1]["h"] = -1
    assert sanitize_daily_bars(broken, now=NOW).empty
    unbounded = sample_bars() * 11
    assert sanitize_daily_bars(unbounded, now=NOW).empty
    duplicate = sample_bars()
    duplicate[-1] = duplicate[-2]
    assert sanitize_daily_bars(duplicate, now=NOW).empty
    assert sanitize_daily_bars([{"t": "bad"}], now=NOW).empty


def test_alpaca_request_budget_uses_explicit_iex_only():
    client = Client()
    rows = fetch_daily_bars("NVDA", now=NOW,
                           api_key="not-a-secret", api_secret="fake", session=client)
    assert len(rows) == 95 and len(client.calls) == 1
    with pytest.raises(ValueError):
        fetch_daily_bars("NVDA/../../x", now=NOW,
                         api_key="not-a-secret", api_secret="fake", session=client)
    assert len(client.calls) == 1
    no_access = Client(FakeResponse(bad=True))
    with pytest.raises(requests.HTTPError):
        fetch_daily_bars("TSLA", now=NOW,
                         api_key="not-a-secret", api_secret="fake", session=no_access)
    assert len(no_access.calls) == 1  # no retry around 401/403/429


def test_private_alert_needs_independent_permission_and_deduplicates():
    client = Client()
    sends = []
    first, state = run(now=NOW, env=ENABLED, client=client,
                       send=lambda msg: sends.append(msg) or SimpleNamespace(message_id=101),
                       private_ready=True)
    assert first["schema"] == SCHEMA
    assert first["status"] == "INTERNAL_RESEARCH"
    assert first["valid_daily_histories"] == 8
    assert first["tickers_published"] is False
    assert first["trade_signals_published"] is False
    assert "source_last_daily_bar" not in first
    assert "RGC" not in str(first) and "NVDA" not in str(first)
    assert not sends and state == {}

    private = {**ENABLED, "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true"}
    sent, state = run(now=NOW, env=private, client=client,
                      send=lambda msg: sends.append(msg) or SimpleNamespace(message_id=102),
                      private_ready=True)
    assert sent["private_delivery"] == "ACCEPTED"
    assert state["last_private_session"] == "2026-10-21"
    assert state["private_message_id"] == 102
    assert len(sends) == 1 and "IEX" in sends[0] and "RGC" in sends[0]
    repeated, repeat_state = run(now=NOW, env=private, client=client, state=state,
                                 send=lambda msg: sends.append(msg), private_ready=True)
    assert "private_delivery" not in repeated and repeat_state == state
    assert len(sends) == 1


def test_failed_telegram_leaves_unsent_and_never_logs_source_data():
    env = {**ENABLED, "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true"}
    def failing(_):
        raise TimeoutError("provider timed out")
    report, state = run(now=NOW, env=env, client=Client(), send=failing,
                        private_ready=True)
    assert report["private_delivery"] == "FAILED"
    assert state == {}
    msg = private_message([{"symbol": "<script>", "day": "2026-10-21"}],
                          "2026-10-21")
    assert "&lt;script&gt;" in msg
    assert "<script>" not in msg
    assert "CALL/PUT" in msg


def test_workflow_single_writer_and_authorization_enforced():
    from pathlib import Path
    import yaml
    workflow = Path(".github/workflows/alpaca-iex-vcp-private.yml").read_text()
    parsed = yaml.safe_load(workflow)
    assert parsed[True]["schedule"] == [{"cron": "30 1 * * 2-6"}]
    assert "ALPACA_INTERNAL_DATA_USE_AUTHORIZED" in workflow
    assert "ALPACA_PRIVATE_ALERTS_AUTHORIZED" in workflow
    assert "state/runtime/public/data/alpaca_iex_vcp_health.json" in workflow
    assert "state/state/alpaca/vcp_private_delivery.json" in workflow
    assert "alpaca_vcp_private" in workflow
    assert "git push origin HEAD:bot-state" in workflow
    assert "stock_watch_charts.json" not in workflow
