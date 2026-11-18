from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml

from options_radar import wiki_attention as wa

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 18, 7, 0, tzinfo=timezone.utc)


def _series(days: int, base: int, last: int) -> dict[str, int]:
    end = date(2026, 11, 17)
    out = {(end - timedelta(days=i)).isoformat(): base for i in range(1, days)}
    out[end.isoformat()] = last
    return out


def test_ratio_uses_previous_60_day_median_and_arabic_level():
    row = wa.summarize("NVDA", _series(68, 10_000, 32_000))
    assert row["status"] == "OK" and row["latest_date"] == "2026-11-17"
    assert row["baseline_median"] == 10_000 and row["baseline_days"] == 60
    assert row["ratio_1d"] == 3.2 and row["level"] == "VERY_HIGH" and row["level_ar"] == "مرتفع جدًا"
    assert row["url"] == "https://en.wikipedia.org/wiki/Nvidia"


def test_short_history_is_reported_not_guessed():
    row = wa.summarize("AAPL", _series(20, 5_000, 9_000))
    assert row["status"] == "INSUFFICIENT_HISTORY" and "ratio_1d" not in row


def test_window_ends_yesterday_and_url_is_human_traffic_only():
    start, end = wa.window(date(2026, 11, 18))
    assert end == date(2026, 11, 17) and (end - start).days == wa.BASELINE_DAYS + 8
    url = wa.url_for("Tesla,_Inc.", start, end)
    # AQS path: /per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}
    assert "/per-article/en.wikipedia/all-access/user/Tesla%2C_Inc./daily/" in url and url.endswith("2026111700")


def test_parse_drops_malformed_rows():
    payload = {"items": [{"timestamp": "2026111700", "views": 5}, {"timestamp": "bad", "views": 1},
                         {"timestamp": "2026111600", "views": -3}, "x"]}
    assert wa.parse_items(payload) == {"2026-11-17": 5}


def _builder():
    spec = importlib.util.spec_from_file_location("build_wiki_attention", ROOT / "scripts/build_wiki_attention.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refusals_are_recorded_and_document_is_context_only():
    builder = _builder()
    body = json.dumps({"items": [{"timestamp": d.replace("-", "") + "00", "views": v}
                                 for d, v in _series(68, 1_000, 2_000).items()]}).encode()

    def fake(url, **_):
        if "Nvidia" in url:
            return SimpleNamespace(ok=False, status=lambda: "REFUSED_HTTP_403", body=b"")
        return SimpleNamespace(ok=True, status=lambda: "OK_HTTP_200", body=body)

    doc = builder.collect(now=NOW, fetch=fake)
    assert doc["errors"] == {"NVDA": "REFUSED_HTTP_403"}
    assert doc["is_price_signal"] is False and doc["research_only"] is True
    assert doc["source"]["license"] == "CC0 1.0" and doc["data_through"] == "2026-11-17"
    assert all(r["status"] == "OK" for r in doc["rows"]) and len(doc["rows"]) == len(wa.LEADERS) - 1


def test_workflow_is_the_single_writer_of_the_attention_file():
    writers = [p.name for p in (ROOT / ".github/workflows").glob("*.yml")
               if "wiki_attention.json" in p.read_text(encoding="utf-8")]
    assert writers == ["wiki-attention.yml"]
    wf = yaml.safe_load((ROOT / ".github/workflows/wiki-attention.yml").read_text(encoding="utf-8"))
    assert "schedule" in wf[True] and "workflow_dispatch" in wf[True]
