from __future__ import annotations

import json

from options_radar import phase60_audit_guard, phase60_sources


def test_empty_process_does_not_overwrite_existing_audit(tmp_path, monkeypatch) -> None:
    audit_path = tmp_path / "source_audit.json"
    audit_path.write_text('{"sentinel": true}', encoding="utf-8")
    monkeypatch.setattr(phase60_sources, "_AUDIT_PATH", audit_path)
    monkeypatch.setattr(
        phase60_sources,
        "_SOURCE_AUDIT",
        {"stocks": {}, "options": {}},
    )

    phase60_audit_guard._guarded_write_audit()

    assert json.loads(audit_path.read_text(encoding="utf-8")) == {"sentinel": True}


def test_nonempty_scanner_audit_is_written(tmp_path, monkeypatch) -> None:
    audit_path = tmp_path / "source_audit.json"
    monkeypatch.setattr(phase60_sources, "_AUDIT_PATH", audit_path)
    monkeypatch.setattr(
        phase60_sources,
        "_SOURCE_AUDIT",
        {
            "stocks": {"AAPL": {"source": "yahoo"}},
            "options": {"AAPL": {"source": "yahoo"}},
        },
    )

    phase60_audit_guard._guarded_write_audit()

    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert payload["stocks"]["AAPL"]["source"] == "yahoo"
    assert payload["options"]["AAPL"]["source"] == "yahoo"
