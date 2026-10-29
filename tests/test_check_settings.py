"""Settings check: no values in the output; private workflows pass the canonical names."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import check_settings as cs

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_WORKFLOWS = ("daily-plan.yml", "private-market-scan.yml", "private-acceptance.yml", "alpaca-iex-vcp-private.yml")
PRIVATE_NAMES = ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED",
                 "ALPACA_PRIVATE_ALERTS_AUTHORIZED", "TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_CHAT_ID", "TELEGRAM_CHAT_ID",
                 "TELEGRAM_OWNER_USERNAME")


class FakeSession:
    def __init__(self, chats):
        self.chats = chats

    def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("/getMe"):
            return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "result": {"id": 1}})
        if url.endswith("/getChat"):
            kind = self.chats.get(params["chat_id"])
            kind, name = kind if isinstance(kind, tuple) else (kind, None)
            body = {"ok": True, "result": {"type": kind, "id": params["chat_id"], "username": name}} if kind else {"ok": False}
            return SimpleNamespace(status_code=200 if kind else 400, json=lambda: body)
        return SimpleNamespace(status_code=200, json=lambda: {"bars": {"SPY": {"c": 1}}})


def test_output_carries_no_values_and_readiness_is_per_path(tmp_path):
    env = {"TELEGRAM_BOT_TOKEN": "tok-secret-123", "TELEGRAM_CHAT_ID": "-100555", "TELEGRAM_OWNER_CHAT_ID": "4242",
           "ALPACA_API_KEY": "AKSECRET", "ALPACA_SECRET_KEY": "SKSECRET", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
           "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true"}
    conn = tmp_path / "connection.json"
    conn.write_text(json.dumps({"chat_id": "-100555", "source": "private_workflow_artifact"}))
    report = cs.check(env, conn, FakeSession({"-100555": "channel", "4242": "private"}))
    text = json.dumps(report)
    for value in ("tok-secret-123", "-100555", "4242", "AKSECRET", "SKSECRET"):
        assert value not in text
    assert report["checks"]["broadcast_source"] == "private_workflow_artifact"
    assert report["checks"]["broadcast_chat_type"] == "channel" and report["checks"]["owner_chat_type"] == "private"
    assert report["ready"] == {"public_telegram": True, "private_price_analysis": True, "private_alerts": True}
    # A channel or group is never the owner's chat.
    same = cs.check({**env, "TELEGRAM_OWNER_CHAT_ID": "-100555"}, conn, FakeSession({"-100555": "channel"}))
    assert same["checks"]["owner_is_broadcast_chat"] is True and same["ready"]["private_alerts"] is False
    # No public channel needed: the resolved one-to-one chat is the owner's, verified by username.
    solo = {k: v for k, v in env.items() if k != "TELEGRAM_OWNER_CHAT_ID"}
    solo.update(TELEGRAM_CHAT_ID="777", TELEGRAM_OWNER_USERNAME="@Ghazi_Owner")
    ok = cs.check(solo, conn, FakeSession({"777": ("private", "ghazi_owner")}))
    assert ok["checks"]["owner_source"] == "BROADCAST_CHAT_VERIFIED_BY_USERNAME"
    assert ok["checks"]["owner_username_matches"] is True and ok["ready"]["private_alerts"] is True
    assert "ghazi_owner" not in json.dumps(ok).lower()
    wrong = cs.check(solo, conn, FakeSession({"777": ("private", "someone")}))
    assert wrong["checks"]["owner_username_matches"] is False and wrong["ready"]["private_alerts"] is False


def test_alpaca_keys_are_not_called_without_the_owner_attestation(tmp_path):
    calls = []

    class Spy(FakeSession):
        def get(self, url, **kw):
            calls.append(url)
            return super().get(url, **kw)

    report = cs.check({"ALPACA_API_KEY": "a", "ALPACA_SECRET_KEY": "b"}, tmp_path / "none.json", Spy({}))
    assert report["checks"]["alpaca_keys"] == "NOT_TESTED_OWNER_ATTESTATION_NOT_RECORDED"
    assert not any("alpaca" in u for u in calls)
    assert report["settings"]["ALPACA_API_KEY"]["received"] == "PRESENT"
    assert report["settings"]["TELEGRAM_OWNER_CHAT_ID"]["received"] == "ABSENT_OR_NOT_PASSED"
    assert report["settings"]["ALPACA_INTERNAL_DATA_USE_AUTHORIZED"]["received"] == "UNSET"
    # A broadcast chat found by the resolve step is not the secret being set.
    resolved = cs.check({"TELEGRAM_CHAT_ID": "-100", "TELEGRAM_CHAT_ID_SECRET_SET": "false"}, tmp_path / "x.json", Spy({}))
    assert resolved["settings"]["TELEGRAM_CHAT_ID"]["received"] == "ABSENT_OR_NOT_PASSED"
    assert resolved["checks"]["broadcast_resolved"] is True


def test_private_workflows_pass_the_canonical_names_and_resolve_the_broadcast_chat():
    for name in PRIVATE_WORKFLOWS:
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for setting in PRIVATE_NAMES:
            assert f"{setting}: ${{{{" in text, (name, setting)
        assert "resolve-telegram-broadcast" in text and "actions: read" in text, name
    # Every Alpaca-bars consumer reads the same feed setting.
    for name in ("daily-plan.yml", "private-market-scan.yml", "private-acceptance.yml"):
        assert "ALPACA_BARS_FEED: ${{ vars.ALPACA_BARS_FEED || 'sip' }}" in (ROOT / ".github/workflows" / name).read_text()
    # The probe's old display label is gone; only canonical names are used anywhere.
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        assert "ALPACA_USE_AUTHORIZED" not in wf.read_text(encoding="utf-8"), wf.name
