"""Telegram ops digest: outage/recovery alerts, one daily digest, delivery log."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


digest = _load("send_ops_digest")
cards = _load("build_platform_scorecards")
NOON = datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)


def _hub(**states):
    return {"datasets": [{"file": f, "data_state": s, "title_ar": f"<{f}>"} for f, s in states.items()]}


class Recorder:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, text):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append(text)
        return SimpleNamespace(message_id=100 + len(self.sent))


def test_first_run_records_states_without_alerting_and_waits_for_noon():
    send = Recorder()
    state, summary = digest.run(hub=_hub(a="DELAYED"), fda=None, smoke=None, state=None,
                                now=NOON.replace(hour=9), mode="scheduled", send=send)
    assert send.sent == [] and summary["sent"] == []
    assert state["states"] == {"a": "DELAYED"} and state["delivery_log"] == []


def test_outage_and_recovery_alert_once_and_licence_changes_do_not():
    send = Recorder()
    prev = {"states": {"a": "DELAYED", "b": "SOURCE_UNAVAILABLE", "c": "DELAYED"}, "last_daily": "2026-10-21"}
    hub = _hub(a="STALE", b="HISTORICAL", c="LICENSE_BLOCKED")
    state, summary = digest.run(hub=hub, fda=None, smoke=None, state=prev, now=NOON, mode="scheduled", send=send)
    assert summary["changes"] == {"down": ["a"], "back": ["b"]}
    assert len(send.sent) == 1 and "توقف" in send.sent[0] and "عاد للعمل" in send.sent[0]
    assert "&lt;a&gt;" in send.sent[0] and "<a>" not in send.sent[0].replace('<a href', '')
    assert "<c>" not in send.sent[0] and "&lt;c&gt;" not in send.sent[0]
    _, summary = digest.run(hub=hub, fda=None, smoke=None, state=state, now=NOON, mode="scheduled", send=send)
    assert len(send.sent) == 1 and summary["sent"] == []


def test_daily_digest_once_per_day_with_message_id_logged():
    send = Recorder()
    fda = {"counts": {"new_molecule_approvals": 2, "class_i_recalls": 1, "matched_to_ticker": 3}}
    smoke = {"generated_at": "2026-10-21T07:00:00Z", "pages": {"x": {"http_status": 200, "errors": []},
                                                              "y": {"http_status": 500, "errors": ["e"]}}}
    state, summary = digest.run(hub=_hub(a="DELAYED", b="LICENSE_BLOCKED"), fda=fda, smoke=smoke,
                                state={"states": {"a": "DELAYED", "b": "LICENSE_BLOCKED"}},
                                now=NOON, mode="scheduled", send=send)
    assert summary["sent"] == ["daily"] and state["last_daily"] == "2026-10-21"
    text = send.sent[0]
    assert "محجوبة بالترخيص 1" in text and "1/2" in text and "جزيئات جديدة معتمدة 2" in text
    assert "ليس توصية تداول" in text
    assert state["delivery_log"][-1] == {"kind": "daily", "sent_at": NOON.isoformat(), "message_id": 101}
    digest.run(hub=_hub(a="DELAYED", b="LICENSE_BLOCKED"), fda=fda, smoke=smoke, state=state,
               now=NOON + timedelta(hours=3), mode="scheduled", send=send)
    assert len(send.sent) == 1


def test_failed_send_keeps_previous_states_so_the_change_is_retried():
    prev = {"states": {"a": "DELAYED"}, "last_daily": "2026-10-21"}
    state, summary = digest.run(hub=_hub(a="STALE"), fda=None, smoke=None, state=prev, now=NOON,
                                mode="scheduled", send=Recorder(fail=True))
    assert summary["failed"].startswith("RuntimeError") and state["states"] == {"a": "DELAYED"}
    assert state["delivery_log"] == []


def test_test_mode_sends_a_delivery_test_and_no_hub_sends_nothing():
    send = Recorder()
    _, summary = digest.run(hub=_hub(a="DELAYED"), fda=None, smoke=None, state=None,
                                now=NOON.replace(hour=3), mode="test", send=send)
    assert summary["sent"] == ["test"] and "اختبار تسليم" in send.sent[0]
    _, summary = digest.run(hub=None, fda=None, smoke=None, state=None, now=NOON, mode="test", send=send)
    assert summary["skipped"] and len(send.sent) == 1


def test_scorecard_reports_delivered_only_from_a_recent_message_id():
    audit = {"checked_at": NOON.isoformat(), "bot_api_responded": True, "destination_api_verified": True}
    log = {"delivery_log": [{"kind": "daily", "sent_at": NOON.isoformat(), "message_id": 7}]}
    assert cards.telegram(audit, NOON + timedelta(hours=2), log)["status"] == "DELIVERED"
    assert cards.telegram(audit, NOON + timedelta(hours=2), {"delivery_log": [
        {"kind": "daily", "sent_at": NOON.isoformat(), "message_id": None}]})["status"] == "API_VERIFIED"
    assert cards.telegram(audit, NOON + timedelta(hours=40), log)["status"] == "STALE"
    assert cards.telegram(None, NOON, None)["status"] == "UNMEASURED"


def test_scorecards_build_reads_the_digest_log(tmp_path):
    state_dir = tmp_path / "state"
    (state_dir / "telegram").mkdir(parents=True)
    (state_dir / "telegram/ops_digest_state.json").write_text(json.dumps(
        {"delivery_log": [{"kind": "test", "sent_at": NOON.isoformat(), "message_id": 9}]}))
    report = cards.build(tmp_path / "data", state_dir, tmp_path / "runtime", NOON, {}, None)
    assert report["scorecards"]["TELEGRAM_DELIVERY"]["status"] == "DELIVERED"


def test_workflow_is_the_single_writer_and_only_sends_when_ready():
    wf = yaml.safe_load((ROOT / ".github/workflows/ops-digest.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["ops-digest"]["steps"]
    send = next(s for s in steps if s.get("id") == "digest")
    assert send["if"] == "env.TELEGRAM_READY == 'true'"
    assert "state/state/telegram/ops_digest_state.json" in send["run"]
    writers = [p for p in (ROOT / ".github/workflows").glob("*.yml")
               if "telegram/ops_digest_state.json" in p.read_text(encoding="utf-8")]
    assert [p.name for p in writers] == ["ops-digest.yml"]
    assert "schedule" in wf[True] and "workflow_run" in wf[True]
