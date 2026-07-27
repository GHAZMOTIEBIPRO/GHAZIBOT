from __future__ import annotations

import json
from types import SimpleNamespace

from options_radar.operations import _read_sec_efts_status
from options_radar.universe import _sec_ticker_map


def test_universe_sec_ticker_map_uses_persistent_snapshot(tmp_path, monkeypatch):
    mapping = tmp_path / "sec_cik_map.json"
    mapping.write_text(json.dumps({"AAPL": "320193", "NVDA": "1045810"}), encoding="utf-8")
    monkeypatch.setattr("options_radar.universe.LOCAL_CIK_MAP", mapping)

    def blocked(*args, **kwargs):
        raise RuntimeError("403 forbidden")

    monkeypatch.setattr("options_radar.universe.requests.get", blocked)
    result = _sec_ticker_map(SimpleNamespace(sec_user_agent="GHAZI test contact@example.com"))
    assert result["0000320193"] == "AAPL"
    assert result["0001045810"] == "NVDA"


def test_sec_fulltext_status_is_public_and_structured(tmp_path, monkeypatch):
    status_path = tmp_path / "sec_efts_status.json"
    status_path.write_text(
        json.dumps(
            {
                "available": False,
                "event_count": 0,
                "http_status": 403,
                "message": "blocked on shared runner",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("options_radar.operations.SEC_EFTS_STATUS", status_path)
    result = _read_sec_efts_status()
    assert result["available"] is False
    assert result["http_status"] == 403
    assert "shared runner" in result["message"]
