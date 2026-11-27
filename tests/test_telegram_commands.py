"""Owner-only Telegram commands: parsing, owner filter, peek never consumes, offset-only state."""
import json
from pathlib import Path

import yaml

from scripts import telegram_commands as tc

ROOT = Path(__file__).resolve().parents[1]


def _update(uid, text, chat_id=42, kind="private"):
    return {"update_id": uid, "message": {"chat": {"id": chat_id, "type": kind}, "text": text}}


def test_parse_known_commands_and_reject_bad_symbols():
    assert tc.parse("/map nvda") == ("map", "NVDA")
    assert tc.parse("/stock@GhaziBot BRK.B") == ("stock", "BRK.B")
    assert tc.parse("/market") == ("market", None)
    assert tc.parse("/map") == ("help", None) and tc.parse("/map ../etc") == ("help", None)
    assert tc.parse("/unknown") == ("help", None) and tc.parse("hello") is None and tc.parse(None) is None


def test_only_the_owners_private_chat_is_answered():
    updates = [_update(1, "/map NVDA"), _update(2, "/map TSLA", chat_id=7), _update(3, "/stock AMD", kind="group"),
               _update(4, "just text"), {"update_id": 5, "channel_post": {"text": "/map X"}}, _update(6, "/status")]
    assert tc.owner_commands(updates, "42") == [(1, "map", "NVDA"), (6, "status", None)]


def test_peek_is_silent_without_configuration(capsys, monkeypatch):
    called = []
    monkeypatch.setattr(tc, "_get_updates", lambda *a, **k: called.append(a) or [])
    assert tc.peek({}) == 0 and called == [] and "PENDING 0" in capsys.readouterr().out
    monkeypatch.setattr(tc, "_get_updates", lambda token, offset=None: called.append(offset) or [_update(9, "/help")])
    tc.peek({"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_CHAT_ID": "42"})
    assert called == [None] and capsys.readouterr().out.strip() == "PENDING 1"  # no offset: nothing consumed


def test_serve_stores_only_the_offset_and_statuses(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(tc, "_get_updates", lambda token, offset=None: [_update(10, "/help"), _update(11, "/map X", 7)])
    import scripts.telegram_transport as transport

    class Receipt:
        message_id = 3

    monkeypatch.setattr(transport, "get_chat", lambda chat: {"type": "private"})
    monkeypatch.setattr(transport, "send_html_message", lambda text, chat_id: sent.append(text) or Receipt())
    env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_OWNER_CHAT_ID": "42", "ALPACA_INTERNAL_DATA_USE_AUTHORIZED": "true",
           "ALPACA_PRIVATE_ALERTS_AUTHORIZED": "true"}
    assert tc.serve(env, tmp_path) == 0
    saved = json.loads((tmp_path / "telegram_commands_offset.json").read_text())
    assert saved["next_offset"] == 12  # the stranger's message is consumed too, never answered
    assert saved["last_results"] == [{"update_id": 10, "command": "help", "status": "DELIVERED"}]
    assert len(sent) == 1 and "/map" in sent[0]


def test_command_workflow_and_orchestrator_peek():
    wf = yaml.safe_load((ROOT / ".github/workflows/telegram-commands.yml").read_text(encoding="utf-8"))
    assert list(wf[True]) == ["workflow_dispatch"]
    text = (ROOT / ".github/workflows/telegram-commands.yml").read_text(encoding="utf-8")
    assert "git add state/telegram/telegram_commands_offset.json" in text and "RUNNER_TEMP" not in text
    steps = wf["jobs"]["serve"]["steps"]
    peek = next(i for i, st in enumerate(steps) if st.get("id") == "peek")
    assert all("pending" in str(st.get("if", "")) for st in steps[peek + 1:])  # nothing installed when idle
    central = (ROOT / ".github/workflows/market-orchestrator.yml").read_text(encoding="utf-8")
    assert "dispatch_if_stale telegram-commands.yml 9" in central and "TELEGRAM_BOT_TOKEN" not in central
