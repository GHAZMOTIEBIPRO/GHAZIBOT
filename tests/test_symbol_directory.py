from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts import build_symbol_directory as sd

NOW = datetime(2026, 10, 26, 6, tzinfo=timezone.utc)
SHA = "a" * 40


def csv_text(rows: int = 500, *, drop: str | None = None, bad: dict | None = None) -> str:
    header = ["Symbol", "Security", "GICS Sector", "GICS Sub-Industry", "Headquarters Location", "Date added",
              "CIK", "Founded"]
    if drop:
        header.remove(drop)
    lines = [",".join(header)]
    for i in range(rows):
        letters = "".join(chr(65 + (i // 26 ** k) % 26) for k in range(3))
        row = {"Symbol": letters, "Security": f"Company {i}", "GICS Sector": "Health Care",
               "GICS Sub-Industry": "Pharmaceuticals", "Headquarters Location": "X", "Date added": "2001-01-02",
               "CIK": str(1000 + i), "Founded": "1900"}
        if bad and i == 0:
            row.update(bad)
        lines.append(",".join(row[h] for h in header))
    return "\n".join(lines) + "\n"


def test_builds_directory_with_attribution_and_scope():
    report = sd.build(csv_text(), {"sha": SHA, "date": "2026-10-26T01:59:54Z"}, NOW)
    assert report["count"] == 500 and report["status"] == "AVAILABLE"
    assert report["point_in_time"] is False
    assert report["source"]["data_commit_sha"] == SHA
    assert "CC BY-SA" in report["source"]["upstream_license"] and "Wikipedia" in report["source"]["attribution"]
    assert "historical tests" in " ".join(report["use"]["not_for"])
    row = report["symbols"][0]
    assert set(row) == {"symbol", "name", "sector", "sector_ar", "sub_industry", "cik", "date_added"}
    assert len(row["cik"]) == 10 and row["sector_ar"] == "الرعاية الصحية"
    # Nothing price-like is carried.
    assert not any(k in json.dumps(report) for k in ("market_cap\"", "price\"", "weight\""))


@pytest.mark.parametrize("kwargs", [
    {"rows": 300},                                   # truncated download
    {"rows": 600},                                   # not the member list
    {"drop": "CIK"},                                 # schema changed upstream
    {"bad": {"Symbol": "not a ticker"}},
    {"bad": {"CIK": "n/a"}},
    {"bad": {"GICS Sector": "Unknown"}},
])
def test_rejects_files_that_do_not_look_like_the_member_list(kwargs):
    with pytest.raises(sd.DirectoryRejected):
        sd.build(csv_text(**kwargs), {"sha": SHA, "date": "x"}, NOW)


def test_main_keeps_previous_file_when_the_source_is_rejected(tmp_path, monkeypatch):
    out = tmp_path / "symbol_directory.json"
    out.write_text('{"previous": true}', encoding="utf-8")
    monkeypatch.setattr(sd, "fetch", lambda: (csv_text(rows=10), {"sha": SHA, "date": "x"}))
    monkeypatch.setattr("sys.argv", ["build_symbol_directory.py", "--output", str(out)])
    assert sd.main() == 1
    assert json.loads(out.read_text(encoding="utf-8")) == {"previous": True}


def test_fetch_reads_the_exact_commit_it_records():
    calls = []

    class Response:
        def __init__(self, payload=None, text=""):
            self.payload, self.text = payload, text

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def get(self, url, **kwargs):
            calls.append(url)
            if "api.github.com" in url:
                return Response([{"sha": SHA, "commit": {"committer": {"date": "2026-10-26T01:59:54Z"}}}])
            return Response(text=csv_text())

    text, commit = sd.fetch(Session())
    assert commit == {"sha": SHA, "date": "2026-10-26T01:59:54Z"}
    assert calls[1].endswith(f"/{SHA}/data/constituents.csv")
