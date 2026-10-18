from datetime import datetime, timezone
from pathlib import Path
import json
import pytest

from scripts.bls_macro_context import SERIES, fetch_bls_json, parse_series, build_snapshot


def payload():
    data = {}
    data["CUUR0000SA0"] = [("2026", "M09", "325"), ("2025", "M09", "315")]
    data["CUUR0000SA0L1E"] = [("2026", "M09", "330"), ("2025", "M09", "320")]
    data["LNS14000000"] = [("2026", "M09", "4.3")]
    data["CES0000000001"] = [("2026", "M09", "160300"), ("2026", "M08", "160190")]
    assert set(data) == set(SERIES)
    return {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
        {"seriesID": name, "data": [
            {"year": year, "period": month, "value": value} for year, month, value in rows
        ]} for name, rows in data.items()
    ]}}


def test_official_monthly_context_is_never_quote_or_signal():
    result = build_snapshot(payload(), now=datetime(2026, 10, 18, tzinfo=timezone.utc))
    assert result["authority"] == "OFFICIAL_MACRO_CONTEXT_ONLY"
    assert result["may_trigger_call_put"] is False
    assert result["is_realtime"] is False
    assert result["indicators"]["cpi_yoy_pct"]["value"] == round(100*(325/315-1), 3)
    assert result["indicators"]["core_cpi_yoy_pct"]["value"] == round(100*(330/320-1), 3)
    assert result["indicators"]["unemployment_pct"]["value"] == 4.3
    assert result["indicators"]["payroll_change_thousands"]["value"] == 110
    assert result["indicators"]["payroll_change_thousands"]["period"] == "2026-09"


def test_missing_comparison_does_not_invent_inflation_rate():
    data = payload()
    data["Results"]["series"][0]["data"] = [{"year":"2026","period":"M09","value":"325"}]
    assert build_snapshot(data)["indicators"]["cpi_yoy_pct"]["value"] is None


def test_bls_excludes_annual_average_and_incomplete_series():
    data = payload()
    data["Results"]["series"][0]["data"].append({"year":"2026","period":"M13","value":"999"})
    assert parse_series(data)["CUUR0000SA0"][0] == ("2026-09", 325)
    data["Results"]["series"].pop()
    with pytest.raises(ValueError, match="Incomplete"):
        parse_series(data)


def test_failed_provider_preserves_last_saved_file(tmp_path):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self, *_): return b'{"status":"REQUEST_NOT_PROCESSED"}'
    def opener(req, timeout):
        assert req.get_method() == "POST"
        assert timeout == 18
        return Response()
    path = tmp_path / "bls_macro.json"
    path.write_text('{"saved":true}')
    with pytest.raises(ValueError, match="rate-limited"):
        fetch_bls_json(opener)
    assert json.loads(path.read_text()) == {"saved": True}


def test_public_panel_has_conservative_schema():
    html = Path("public/index.html").read_text(encoding="utf-8")
    js = Path("public/bls-macro.js").read_text(encoding="utf-8")
    assert 'id="tab-macro"' in html
    assert 'data-tab="macro"' in html
    assert "bls_macro.json" in js
    assert "is_realtime" in js
    assert "may_trigger_call_put" in js
