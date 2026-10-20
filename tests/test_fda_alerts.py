import importlib.util
import json
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fda = _load("fda_events_for_alerts", "options_radar/fda_events.py")
alerts = _load("send_fda_alerts_under_test", "scripts/send_fda_alerts.py")
NOW = datetime(2026, 10, 20, 21, 30, tzinfo=timezone.utc)


def _event(event_id, day, importance="HIGH", event_type="APPROVAL_ORIGINAL", **extra):
    return {"event_id": event_id, "date": day, "importance": importance, "event_type": event_type,
            "sponsor": "VERTEX PHARMS", "ticker": "VRTX", "match_method": "reviewed_sponsor_alias",
            "application_kind": "NDA", "application_number": "NDA217123", "products": ["NEWDRUG"],
            "official_url": "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?ApplNo=217123", **extra}


def _report(*events):
    return {"schema": "ghazi.fda_events.v1", "approvals": [e for e in events if e["event_type"] != "RECALL"],
            "recalls": [e for e in events if e["event_type"] == "RECALL"]}


class Sender:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def __call__(self, text):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append(text)
        return type("R", (), {"message_id": len(self.sent)})()


def test_first_run_seeds_without_sending_then_new_events_send_once():
    sender = Sender()
    report = _report(_event("A", "2026-10-15"))
    state, summary = alerts.run(report, None, now=NOW, max_age_days=14, max_new=5, send=sender)
    assert summary["mode"] == "seeded" and sender.sent == [] and "A" in state["events"]

    report = _report(_event("A", "2026-10-15"), _event("B", "2026-10-18"))
    state, summary = alerts.run(report, state, now=NOW, max_age_days=14, max_new=5, send=sender)
    assert summary["sent"] == 1 and len(sender.sent) == 1 and state["events"]["B"]["status"] == "sent"

    state, summary = alerts.run(report, state, now=NOW, max_age_days=14, max_new=5, send=sender)
    assert summary["sent"] == 0 and len(sender.sent) == 1


def test_only_recent_high_events_are_candidates():
    report = _report(_event("old", "2026-09-30"), _event("low", "2026-10-19", importance="LOW"),
                     _event("future", "2026-10-25"), _event("ok", "2026-10-19"),
                     _event("rc", "2026-10-19", event_type="RECALL", classification="Class I"))
    assert [e["event_id"] for e in alerts.candidates(report, NOW.date(), 14)] == ["rc", "ok"]


def test_failure_stops_and_leaves_event_unsent_and_cap_applies():
    state = {"schema": alerts.STATE_SCHEMA, "events": {}}
    report = _report(*[_event(f"E{i}", "2026-10-19") for i in range(7)])
    new_state, summary = alerts.run(report, state, now=NOW, max_age_days=14, max_new=5, send=Sender(fail=True))
    assert summary["failed"].startswith("RuntimeError") and new_state["events"] == {}
    new_state, summary = alerts.run(report, state, now=NOW, max_age_days=14, max_new=5, send=Sender())
    assert summary["sent"] == 5 and summary["pending"] == 2


def test_message_is_escaped_labelled_and_drops_unsafe_links():
    text = alerts.format_message(_event("X", "2026-10-19", sponsor="<b>Evil</b>", ticker=None,
                                        official_url="javascript:alert(1)"))
    assert "&lt;b&gt;Evil&lt;/b&gt;" in text and "javascript" not in text
    assert "بلا رمز" in text and "ليست توصية" in text and "CC0" in text
    good = alerts.format_message(_event("Y", "2026-10-19"))
    assert "<b>VRTX</b>" in good and 'href="https://www.accessdata.fda.gov/' in good
    recall = alerts.format_message(_event("R", "2026-10-19", event_type="RECALL", classification="Class I",
                                          reason="Salmonella", product="Tablets"))
    assert "Class I" in recall and "Salmonella" in recall


def test_only_new_molecules_are_high_and_generics_are_low():
    def app(number, klass="UNKNOWN"):
        return {"application_number": number, "sponsor_name": "X Co",
                "submissions": [{"submission_type": "ORIG", "submission_number": "1", "submission_status": "AP",
                                 "submission_status_date": "20261015",
                                 "submission_class_code_description": klass}]}
    rows = [app("ANDA212345"), app("NDA212346", "Type 1 - New Molecular Entity"),
            app("BLA761234", "Type 1 - New Molecular Entity"), app("NDA212347", "Type 2 - New Active Ingredient"),
            app("NDA212348", "Type 5 - New Formulation or New Manufacturer"), app("NDA212349")]
    events = fda.approval_events(rows, {}, date(2026, 9, 21), date(2026, 10, 20))
    by_number = {e["application_number"]: e["importance"] for e in events}
    assert by_number == {"ANDA212345": "LOW", "NDA212346": "HIGH", "BLA761234": "HIGH", "NDA212347": "HIGH",
                         "NDA212348": "MEDIUM", "NDA212349": "MEDIUM"}
    report = fda.build(events, [], generated_at="x", start=date(2026, 9, 21), end=date(2026, 10, 20))
    assert report["counts"]["new_drug_or_biologic_approvals"] == 5
    assert report["counts"]["new_molecule_approvals"] == 3


def test_reviewed_sponsor_aliases_match_fda_spellings_without_collisions():
    data = json.loads((ROOT / "data" / "fda_sponsor_aliases.json").read_text(encoding="utf-8"))
    company = json.loads((ROOT / "data" / "company_aliases.json").read_text(encoding="utf-8"))
    index = fda.build_name_index(company, data["aliases"])
    assert fda.match_ticker("MERCK SHARP DOHME", index) == ("MRK", "reviewed_sponsor_alias")
    assert fda.match_ticker("AMNEAL PHARMS NY", index) == ("AMRX", "reviewed_sponsor_alias")
    assert fda.match_ticker("Merck KGaA", index) == (None, "unmatched")
    keys = {}
    for ticker, names in data["aliases"].items():
        assert ticker.isupper() and names
        for name in names:
            key = fda.normalise(name)
            assert len(key) >= 3 and keys.setdefault(key, ticker) == ticker, name
    # A spelling mapped to two tickers is dropped, not guessed.
    clash = fda.build_name_index({}, {"AAA": ["Same Name Inc"], "BBB": ["Same Name Corp"]})
    assert fda.match_ticker("Same Name", clash) == (None, "unmatched")


def test_workflow_is_single_writer_and_gated():
    wf = yaml.safe_load((ROOT / ".github/workflows/fda-events.yml").read_text(encoding="utf-8"))
    steps = {s.get("name"): s for s in wf["jobs"]["update-fda-events"]["steps"]}
    send = steps["Alert important FDA events (deduplicated, no backlog)"]
    assert send["if"] == "env.TELEGRAM_READY == 'true'" and "state/fda/fda_alert_state.json" in send["run"]
    assert steps["Publish the FDA events document and alert state"]["if"] == "always() && steps.build.outcome == 'success'"
    writers = [p.name for p in (ROOT / ".github/workflows").glob("*.yml")
               if "fda_alert_state.json" in p.read_text(encoding="utf-8")]
    assert writers == ["fda-events.yml"]
