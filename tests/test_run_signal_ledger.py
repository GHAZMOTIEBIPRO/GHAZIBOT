from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

import pytest

from options_radar import signal_ledger as sl
from scripts import run_signal_ledger as runner
from scripts import send_strict_options_alerts as sender

T0 = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
OCC = "AMD261106C00250000"


def _row(at, bid, ask, source="intrinio-opra"):
    return {"contract_symbol": OCC, "symbol": "AMD", "side": "CALL", "strike": 250, "expiration": "2026-11-06",
            "bid": bid, "ask": ask, "quote_timestamp": at.isoformat(), "source": source,
            "underlying_price": 248.2, "telegram_eligible": True,
            "v11_decision": {"approved": True, "state": "CONFIRMED", "blockers": []}}


def _write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _args(tmp_path, payload, sender_state):
    return argparse.Namespace(
        payload=_write(tmp_path, "payload.json", payload),
        sender_state=_write(tmp_path, "sender.json", sender_state),
        ledger=str(tmp_path / "ledger.json"), public=str(tmp_path / "public.json"))


@pytest.fixture(autouse=True)
def _no_telegram(monkeypatch):
    monkeypatch.delenv("SIGNAL_LEDGER_TELEGRAM", raising=False)
    monkeypatch.delenv("SIGNAL_LEDGER_LINKS", raising=False)
    monkeypatch.delenv("PUBLIC_DISPLAY_TERMS_CONFIRMED", raising=False)


def test_adopts_delivered_alert_monitors_and_redacts_public(tmp_path):
    sent = {"sent": {"AMD:CALL": {"kind": "options", "contract_symbol": OCC, "message_id": 55,
                                  "sent_at": (T0 + timedelta(seconds=3)).isoformat()}}}
    report = runner.run(_args(tmp_path, {"contracts": [_row(T0, 4.9, 5.0)]}, sent), now=T0 + timedelta(seconds=10))
    assert report["signals"] == 1
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    signal = next(iter(ledger["signals"].values()))
    assert signal["telegram"]["message_id"] == 55 and signal["state"] == sl.WATCHING
    assert signal["signal_id"] == sl.signal_id_for(OCC, "2026-11-04")

    # next cycle: a live quote inside the zone -> paper entry; Telegram is off so nothing is sent
    t1 = T0 + timedelta(minutes=2)
    report = runner.run(_args(tmp_path, {"contracts": [_row(t1, 4.95, 5.05)]}, sent), now=t1)
    assert report["state_changes"] == 1 and report["telegram"]["skipped"] == 1
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert next(iter(ledger["signals"].values()))["state"] == sl.PAPER_ACTIVE

    # same cycle replayed: idempotent
    report = runner.run(_args(tmp_path, {"contracts": [_row(t1, 4.95, 5.05)]}, sent), now=t1 + timedelta(seconds=30))
    assert report["state_changes"] == 0 and report["signals"] == 1

    public = json.loads((tmp_path / "public.json").read_text())
    shown = public["signals"][0]
    assert shown["levels"] == {"status": "LICENSE_BLOCKED"}  # intrinio has no recorded public-display right
    assert "message_id" not in shown["telegram"] and public["decision_authority"] is False


def test_delivered_alert_missing_from_payload_is_recorded_not_invented(tmp_path):
    sent = {"sent": {"AMD:CALL": {"kind": "options", "contract_symbol": OCC, "message_id": 9,
                                  "sent_at": T0.isoformat()}}}
    report = runner.run(_args(tmp_path, {"contracts": []}, sent), now=T0)
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert report["signals"] == 0 and ledger["unmonitored_alerts"]


def test_refuses_to_overwrite_foreign_ledger(tmp_path):
    (tmp_path / "ledger.json").write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        runner.run(_args(tmp_path, {}, {"sent": {}}), now=T0)


def test_payload_rows_keep_the_freshest_quote():
    old, new = _row(T0, 1, 1.1), _row(T0 + timedelta(minutes=1), 2, 2.1)
    rows = runner.payload_rows({"contracts": [new], "top_calls": [old]})
    assert rows[OCC]["bid"] == 2


def test_sender_link_is_off_by_default_and_deterministic_when_on(monkeypatch):
    row = _row(T0, 4.9, 5.0)
    assert sender._signal_page_link(row, now=T0) == ""
    monkeypatch.setenv("SIGNAL_LEDGER_LINKS", "1")
    link = sender._signal_page_link(row, now=T0)
    assert sl.signal_url(sl.signal_id_for(OCC, "2026-11-04")) in link
    assert sender._signal_page_link({"contract_symbol": "AMD:CALL:x"}, now=T0) == ""
