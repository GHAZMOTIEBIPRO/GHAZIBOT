"""Acceptance run on fixtures (synthetic: not a live result) and private-data protection in workflows."""
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml

from options_radar import output_policy as op
from scripts import private_acceptance as pa

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)
OWNER = {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
         "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true", "TELEGRAM_OWNER_CHAT_ID": "777", "TELEGRAM_CHAT_ID": "-100"}


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class Session:
    def get(self, url, params=None, headers=None, timeout=None):
        from tests.test_build_daily_plan import _bars_payload
        start, end = datetime.fromisoformat(params["start"]), datetime.fromisoformat(params["end"])
        if params["timeframe"] == "1Day":
            first = start.replace(hour=4, minute=0)
            return Response(_bars_payload(first, int((end - first).total_seconds() // 86400) + 1, 24 * 60))
        return Response(_bars_payload(start, int((end - start).total_seconds() // 300), 5))


def test_sample_uses_an_index_etf_a_leader_and_a_radar_candidate():
    cats = {"watchlist": [{"symbol": "GSK", "universe": "KNOWN_LARGE_ISSUER_LIST"},
                          {"symbol": "RXRX", "universe": "MARKET_CAP_UNVERIFIED"}]}
    assert pa.sample(cats) == ["SPY", "AAPL", "RXRX"] and pa.sample(None) == ["SPY", "AAPL"]


def _sender(env):
    def send(text, captured):
        return op.deliver_private(text, sources=["alpaca_iex"], env=env, get_chat=lambda c: {"type": "private"},
                                  send=lambda body, chat: captured.append(body) or SimpleNamespace(message_id=9))
    return send


def test_end_to_end_on_fixtures_passes_only_when_sent_equals_saved(tmp_path):
    out = tmp_path / "private.json"
    report = pa.run(NOW, OWNER, None, out, session=Session(), send=_sender(OWNER))
    assert report["result"] == "PASS" and report["message_matches_saved"] is True
    for sym in ("SPY", "AAPL"):
        assert all(report["symbols"][sym]["checks"].values())
        assert {"daily", "weekly", "4h", "1h", "15m", "5m"} <= set(report["symbols"][sym]["frames"])
    # the log report carries no prices
    assert '"close"' not in json.dumps(report) and '"high"' not in json.dumps(report)
    saved = json.loads(out.read_text())
    assert pa.render(saved) and saved["facts"]["last_closed_session"] == "2026-10-23"
    # without the owner's private-alert permission nothing is sent and the run fails
    no_alerts = {**OWNER, "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "false"}
    denied = pa.run(NOW, no_alerts, None, out, session=Session(), send=_sender(no_alerts))
    assert denied["delivery"] == "DENIED_BY_POLICY" and denied["result"] == "FAIL"
    assert pa.run(NOW, {}, None, out, session=Session())["result"] == "NOT_RUN"


def test_workflows_with_alpaca_secrets_never_publish_private_data():
    with_keys = []
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        if "${{ secrets.ALPACA_API_KEY }}" not in text:  # presence booleans (!= '') carry no key
            continue
        with_keys.append(path.name)
        assert "actions/cache" not in text, path.name
        wf = yaml.safe_load(text)
        for job in wf["jobs"].values():
            for step in job.get("steps", []):
                if "upload-artifact" in str(step.get("uses", "")):
                    uploaded = str(step["with"]["path"])
                    assert "alpaca" not in uploaded.lower() and "private" not in uploaded.lower(), (path.name, uploaded)
        for line in text.splitlines():
            if "git add" in line:  # a delivery receipt (date + message id) may be kept; private results never
                assert not any(x in line for x in ("private_plan", "private_scan", "private_acceptance", "RUNNER_TEMP")), \
                    (path.name, line)
        if path.name in ("private-market-scan.yml", "private-acceptance.yml"):
            wf = yaml.safe_load(text)
            assert wf["permissions"] == {"contents": "read"}  # cannot push to any branch
            assert "RUNNER_TEMP" in text
    # only owner-private workflows receive the keys; public publishers never do
    assert sorted(with_keys) == ["alpaca-iex-vcp-private.yml", "alpaca-private-probe.yml", "daily-plan.yml",
                                 "private-acceptance.yml", "private-data-access.yml", "private-market-scan.yml"]


def test_legacy_settings_never_load_alpaca_keys_outside_private_scope(monkeypatch):
    import importlib

    from options_radar import settings as settings_module
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "s")
    monkeypatch.delenv("GHAZI_PIPELINE_SCOPE", raising=False)
    public = importlib.reload(settings_module).Settings()
    assert public.alpaca_api_key is None and public.alpaca_secret_key is None
    monkeypatch.setenv("GHAZI_PIPELINE_SCOPE", "private")
    private = importlib.reload(settings_module).Settings()
    assert private.alpaca_api_key == "k"
    monkeypatch.delenv("GHAZI_PIPELINE_SCOPE")
    importlib.reload(settings_module)

