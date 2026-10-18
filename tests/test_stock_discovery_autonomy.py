"""Regression checks for hands-off stock discovery and bounded free providers."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from options_radar.free_public_intelligence import google_issuer_attention
from scripts.build_stock_watch_charts import (
    FIVE_MIN, WATCH, collect, load_dynamic_symbols, pack_symbol,
)

NOW = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)


def decision_file(tmp_path, *, age=timedelta(minutes=5)):
    p = tmp_path / "decision_brief.json"
    rows = [
        {"symbol": "RGC", "score": 100},
        {"symbol": "SPX", "score": 100},
        {"symbol": "../", "score": 100},
        {"symbol": "NEWX", "score": 95},
        {"symbol": "NEWY", "score": 94},
        {"symbol": "NEWZ", "score": 93},
        {"symbol": "NEWQ", "score": 92},
        {"symbol": "NEWV", "score": 91},
        {"symbol": "NEWX", "score": 90},
        {"symbol": "NOTVALID123456", "score": 89},
        {"symbol": "OUT", "score": float("nan")},
    ]
    p.write_text(json.dumps({
        "schema": "ghazi.public_decision.v1",
        "source_generated_at": (NOW - age).isoformat(),
        "stocks": rows,
    }), encoding="utf-8")
    return p


def test_discovery_is_recent_bounded_safe_and_rotates(tmp_path):
    path = decision_file(tmp_path)
    first = load_dynamic_symbols(path, now=NOW)
    later = load_dynamic_symbols(path, now=NOW + timedelta(hours=6))
    assert len(first) == len(later) == 4
    assert first[:2] == later[:2] == ("NEWX", "NEWY")
    assert first != later
    assert set(first).isdisjoint({"SPX", "RGC", "../", "NOTVALID123456", "OUT"})
    assert load_dynamic_symbols(path, now=NOW + timedelta(days=4)) == ()
    assert load_dynamic_symbols(path, now=NOW - timedelta(hours=1)) == ()


def test_discovery_rejects_bad_json_and_future_or_untrusted_report(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_dynamic_symbols(path, now=NOW) == ()
    path.write_text(json.dumps({
        "schema": "other",
        "generated_at": NOW.isoformat(),
        "stocks": [{"symbol": "NEWX", "score": 99}],
    }), encoding="utf-8")
    assert load_dynamic_symbols(path, now=NOW) == ()
    assert load_dynamic_symbols(Path("/nonexistent/ghazi.json"), now=NOW) == ()


def candles(interval):
    if interval == "1d":
        idx = pd.bdate_range("2026-06-01", periods=40, tz="America/New_York")
    else:
        idx = pd.date_range("2026-10-16 09:30", periods=60, freq=interval,
                            tz="America/New_York")
    close = [10 + .05 * n for n in range(len(idx))]
    return pd.DataFrame({
        "Open": close, "High": [v + .4 for v in close],
        "Low": [v - .4 for v in close], "Close": close,
        "Volume": [100] * len(close),
    }, index=idx)


def test_new_radar_stock_gets_real_bars_and_keeps_research_only():
    rows = pack_symbol("NEWX", candles("1d"), candles("15min"), candles("5min"),
                       now=NOW, dynamic_watch=("NEWX",))
    assert rows["category"] == "RADAR_DISCOVERY_WATCH"
    assert rows["options_execution_grade"] is False
    assert rows["market_cap_verified"] is False
    assert "1d" in rows["intervals"]
    assert "15m" in rows["intervals"]
    assert "5m" in rows["intervals"]
    assert pack_symbol("NEWX", candles("1d"), None, None, now=NOW) is None
    assert FIVE_MIN == frozenset(WATCH)


def test_new_symbols_use_same_single_state_file_without_fake_quotes():
    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, *, period, interval, auto_adjust, prepost):
            if self.symbol == "NEWY":
                return pd.DataFrame()
            return candles({"1d": "1d", "15m": "15min", "5m": "5min"}[interval])

    data = collect(now=NOW, provider=SimpleNamespace(Ticker=Ticker),
                   delay=lambda _: None, dynamic_symbols=("NEWX", "NEWY", "SPX"))
    assert data["coverage"]["requested"] == 18
    assert data["coverage"]["discovered_symbols"] == ["NEWX", "NEWY"]
    assert data["coverage"]["discovered_with_charts"] == 1
    assert "NEWX" in data["symbols"]
    assert "NEWY_1d" in data["coverage"]["errors"]
    assert data["quote_execution_eligible"] is False


def test_complete_curated_free_issuer_news_without_extra_calls():
    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, *, params=None, headers=None, timeout=None):
            self.calls.append(params["q"])
            return SimpleNamespace(
                content=b'<rss version="2.0"><channel></channel></rss>',
                raise_for_status=lambda: None,
            )

    session = Session()
    rows, errors = google_issuer_attention(
        ["BNAI", "SOFI", "MSFT", "AVGO"], session=session, now=NOW,
    )
    assert rows == [] and errors == {}
    assert len(session.calls) == 4
    assert any("Brand Engagement Network" in q for q in session.calls)
    assert any("SoFi Technologies" in q for q in session.calls)
    assert any("Microsoft Corporation" in q for q in session.calls)
    assert any("Broadcom Inc." in q for q in session.calls)


def test_runtime_and_frontend_wiring_for_automatic_new_tickers():
    workflow = Path(".github/workflows/stock-watch-charts.yml").read_text()
    js = Path("public/terminal-hub.js").read_text()
    assert "--discovery-source state/runtime/public/data/decision_brief.json" in workflow
    assert "ghazi.stock_charts.v1" in js
    assert "const dynamic=[...scan.map" in js
    assert "لا يوجد عنوان خبر مطابق" in js
