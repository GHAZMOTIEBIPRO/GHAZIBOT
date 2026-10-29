from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts import finra_short_volume_private as fx

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


def test_no_request_without_approval_and_credentials():
    assert fx.gate({}) == "NOT_APPROVED"
    assert fx.gate({"FINRA_API_AUTOMATION_APPROVED": "true"}) == "CREDENTIALS_MISSING"
    assert fx.gate({"FINRA_API_AUTOMATION_APPROVED": "true", "FINRA_API_CLIENT_ID": "x"}) == "CREDENTIALS_MISSING"
    assert fx.gate({"FINRA_API_AUTOMATION_APPROVED": "true", "FINRA_API_CLIENT_ID": "x",
                    "FINRA_API_CLIENT_SECRET": "y"}) == "READY"


def test_public_paths_are_refused(tmp_path):
    assert fx.is_public_path(Path("state/runtime/public/data/finra.json"))
    assert fx.is_public_path(Path("public/finra.json"))
    assert fx.is_public_path(Path("data/live/finra.json"))
    assert not fx.is_public_path(tmp_path / "finra.json")
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "finra_short_volume_private.py"), "--symbols", "AAPL",
                          "--output", "public/finra.json"], capture_output=True, text=True, cwd=tmp_path, check=False)
    assert out.returncode == 2 and not (tmp_path / "public" / "finra.json").exists()


def test_skipped_run_writes_status_only(tmp_path):
    out = tmp_path / "finra.json"
    env = {"PATH": "/usr/bin:/bin"}
    subprocess.run([sys.executable, str(ROOT / "scripts" / "finra_short_volume_private.py"), "--symbols", "AAPL",
                    "--output", str(out)], env=env, check=True, capture_output=True, cwd=ROOT)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "NOT_APPROVED" and data["symbols"] == [] and data["public_display"] is False


def test_summary_is_volume_of_the_latest_day_not_short_interest():
    rows = [{"tradeReportDate": "2026-10-27", "shortParQuantity": 100, "totalParQuantity": 400, "reportingFacilityCode": "N"},
            {"tradeReportDate": "2026-10-28", "shortParQuantity": 300, "shortExemptParQuantity": 5, "totalParQuantity": 1000,
             "reportingFacilityCode": "N"},
            {"tradeReportDate": "2026-10-28", "shortParQuantity": 200, "totalParQuantity": 1000, "reportingFacilityCode": "Q"}]
    got = fx.summarise("AAPL", rows)
    assert got["trade_date"] == "2026-10-28" and got["short_volume"] == 500 and got["reported_volume"] == 2000
    assert got["short_volume_share"] == 0.25 and got["facilities"] == ["N", "Q"]
    assert got["measure"] == "SHORT_SALE_VOLUME_NOT_SHORT_INTEREST" and got["squeeze_inference"] is False


class _R:
    def __init__(self, code, body):
        self.status_code, self._body = code, body

    def json(self):
        return self._body


class _S:
    def __init__(self, token_code=200):
        self.token_code, self.calls = token_code, []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        if url == fx.TOKEN_URL:
            return _R(self.token_code, {"access_token": "t"})
        return _R(200, [{"tradeReportDate": "2026-10-28", "shortParQuantity": 1, "totalParQuantity": 4}])


def test_token_failure_stops_before_any_data_request():
    env = {"FINRA_API_CLIENT_ID": "x", "FINRA_API_CLIENT_SECRET": "y"}
    s = _S(token_code=401)
    assert fx.fetch(s, env, ["AAPL"], NOW) == ("TOKEN_HTTP_401", [])
    assert [u for u, _ in s.calls] == [fx.TOKEN_URL]
    s = _S()
    status, rows = fx.fetch(s, env, ["AAPL"], NOW)
    assert status == "OK" and rows[0]["short_volume_share"] == 0.25
    assert s.calls[1][1]["headers"]["Authorization"] == "Bearer t"
