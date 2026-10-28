"""Alpaca Basic IEX authorized internal research: no data publication or false alerts."""
from __future__ import annotations

import subprocess
import sys
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
    authorized_feed,
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
    def __init__(self, response: FakeResponse | None = None, *, feed: str = "iex"):
        self.feed = feed
        self.calls = []
        self.response = response or FakeResponse()

    def get(self, url, *, params, headers, timeout):
        self.calls.append((url, dict(params), dict(headers), timeout))
        assert url.startswith(ENDPOINT)
        assert headers["APCA-API-KEY-ID"] == "not-a-secret"
        assert headers["APCA-API-SECRET-KEY"] == "fake"
        assert params["feed"] == self.feed
        assert params["end"] == "2026-10-22"  # fully completed previous NY days only
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


def test_gated_run_imports_without_yahoo_dependencies():
    """CI must prevent an eager market-package import on the blocked path."""
    import ast
    from pathlib import Path

    module = ast.parse(Path("scripts/alpaca_vcp_private.py").read_text(encoding="utf-8"))
    global_imports = [
        stmt.module for stmt in module.body if isinstance(stmt, ast.ImportFrom)
    ]
    assert "options_radar.vcp_minervini_shadow" not in global_imports
    assert "options_radar" not in global_imports
    assert "yfinance" not in global_imports


def test_denied_source_preserves_only_safe_dedupe_state():
    from scripts.alpaca_vcp_private import clean_delivery_state

    previously = {
        "last_private_session": "2026-10-21", "private_message_id": 101,
        "symbol": "SECRET_SOURCE_SYMBOL", "raw_ohlc": [100.0, 102.0],
        "token": "not-a-real-secret",
    }
    assert clean_delivery_state(previously) == {
        "last_private_session": "2026-10-21", "private_message_id": 101,
    }
    out, state = run(now=NOW, env={}, state=previously, client=Client())
    assert out["status"] == "PROVIDER_TERMS_UNATTESTED"
    assert state == clean_delivery_state(previously)
    assert "SECRET_SOURCE_SYMBOL" not in str(out) and "token" not in state
    assert clean_delivery_state({
        "last_private_session": "not-a-date", "private_message_id": True,
        "something": "wrong",
    }) == {}


def test_private_telegram_without_confirmed_receipt_is_not_marked_sent():
    enabled = {**ENABLED, "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true"}
    outcome, state = run(now=NOW, env=enabled, client=Client(),
                         private_ready=True, send=lambda message: SimpleNamespace(
                             message_id=None
                         ))
    assert outcome["private_delivery"] == "UNCONFIRMED"
    assert "last_private_session" not in state
    assert "private_message_id" not in state


def test_historical_sip_selection_requires_separate_license_attestation():
    assert authorized_feed({}) == "iex"
    assert authorized_feed({"ALPACA_HISTORICAL_SIP_INTERNAL_AUTHORIZED": "false"}) == "iex"
    assert authorized_feed({"ALPACA_HISTORICAL_SIP_INTERNAL_AUTHORIZED": "true"}) == "sip"
    assert authorization({"ALPACA_HISTORICAL_SIP_INTERNAL_AUTHORIZED": "true",
                          "ALPACA_API_KEY": "not-a-secret", "ALPACA_SECRET_KEY": "fake"}
                         ) == "PROVIDER_TERMS_UNATTESTED"
    denied = Client(feed="sip")
    out, state = run(now=NOW, env={"ALPACA_HISTORICAL_SIP_INTERNAL_AUTHORIZED": "true"},
                     client=denied)
    assert out["status"] == "PROVIDER_TERMS_UNATTESTED"
    assert not denied.calls and state == {}


def test_authorized_historical_sip_daily_vcp_is_not_realtime_or_independent():
    env = {**ENABLED, "ALPACA_HISTORICAL_SIP_INTERNAL_AUTHORIZED": "true",
           "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true"}
    client = Client(feed="sip")
    sent = []
    result, state = run(now=NOW, env=env, client=client,
                        send=lambda value: sent.append(value)
                        or SimpleNamespace(message_id=711),
                        private_ready=True)
    assert result["status"] == "INTERNAL_RESEARCH"
    assert result["source_kind"] == "HISTORICAL_SIP_ONLY_NOT_REALTIME"
    assert result["valid_daily_histories"] == 8
    assert result["independent_source_confirmation"] is False
    assert result["option_quote_verified"] is False
    assert result["execution_authority"] is False
    assert result["raw_market_data_published"] is False
    assert result["tickers_published"] is False
    assert "RGC" not in str(result)
    assert state["private_message_id"] == 711
    assert len(sent) == 1
    assert "SIP تاريخي مكتمل" in sent[0]
    assert "ليست بثًا لحظيًا" in sent[0]
    assert all(call[1]["feed"] == "sip" for call in client.calls)
    assert all(call[1]["end"] == "2026-10-22" for call in client.calls)
    frame = sanitize_daily_bars(sample_bars(), now=NOW)
    shadow = vcp_trend_shadow(frame, source_family="alpaca_historical_sip")
    assert shadow["available"] is True
    assert shadow["independent_confirmation"] is False
    assert shadow["option_execution_eligible"] is False


def test_historical_sip_rejection_does_not_fallback_to_iex_or_emit_alert():
    env = {**ENABLED, "ALPACA_HISTORICAL_SIP_INTERNAL_AUTHORIZED": "true",
           "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true"}
    client = Client(FakeResponse(bad=True), feed="sip")
    sent = []
    result, state = run(now=NOW, env=env, client=client,
                        send=lambda msg: sent.append(msg),
                        private_ready=True)
    assert result["status"] == "INTERNAL_NO_VALID_BARS"
    assert result["valid_daily_histories"] == 0
    assert result["fetch_errors"] == 8
    assert result["source_kind"] == "HISTORICAL_SIP_ONLY_NOT_REALTIME"
    assert not sent and state == {}
    assert len(client.calls) == 8
    assert all(call[1]["feed"] == "sip" for call in client.calls)


def test_sip_endpoint_never_uses_unapproved_feed_or_current_session():
    client = Client(feed="sip")
    got = fetch_daily_bars("AAPL", now=NOW, api_key="not-a-secret",
                           api_secret="fake", session=client, feed="sip")
    assert len(got) == 95
    assert client.calls[0][1]["end"] == "2026-10-22"
    with pytest.raises(ValueError):
        fetch_daily_bars("AAPL", now=NOW, api_key="not-a-secret",
                         api_secret="fake", session=client, feed="opra")
    assert len(client.calls) == 1


def test_blocked_run_starts_without_the_full_project_dependencies():
    # The no-permission run installs only pandas and requests; building the sender
    # must not import the options_radar package (it imports yfinance).
    code = ("import sys; sys.modules['yfinance'] = None; "
            "from scripts.alpaca_vcp_private import owner_send; owner_send({}); print('ok')")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
    assert done.stdout.strip() == "ok", done.stderr[-400:]
