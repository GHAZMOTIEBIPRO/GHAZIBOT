import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from options_radar import market_bars as bars
from options_radar import source_permissions as sp
from options_radar import universe
from options_radar.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def closed_gates(monkeypatch):
    for gate in sp.GATES.values():
        monkeypatch.delenv(gate["variable"], raising=False)


def _no_request(*_args, **_kwargs):
    pytest.fail("no request may leave the runner while the gate is closed")


def test_every_gate_is_closed_unless_exactly_true(monkeypatch):
    for name, gate in sp.GATES.items():
        assert sp.allowed(name) is False
        for value in ("1", "yes", "TRUE ", "false"):
            monkeypatch.setenv(gate["variable"], value)
            assert sp.allowed(name) is (value.strip().lower() == "true")
        monkeypatch.setenv(gate["variable"], "true")
        assert sp.allowed(name) is True
        monkeypatch.delenv(gate["variable"])


def test_yahoo_bar_transports_refuse_before_any_request(monkeypatch):
    monkeypatch.setattr(bars.yf, "download", _no_request)
    with pytest.raises(sp.SourceTermsBlocked):
        bars._yahoo("SPY", period="1mo", interval="1d")
    with pytest.raises(sp.SourceTermsBlocked):
        bars._yahooquery("SPY", period="1mo", interval="1d")
    sources = {row["name"]: row["configured"] for row in bars.configured_bar_sources(Settings())}
    assert sources["yahoo"] is False and sources["yahooquery"] is False


def test_fallback_chain_reports_terms_block(monkeypatch):
    monkeypatch.setattr(bars.yf, "download", _no_request)
    monkeypatch.setattr(bars, "_provider_names", lambda settings, intraday: ["yahooquery", "yahoo"])
    with pytest.raises(RuntimeError, match="SOURCE_TERMS_BLOCKED"):
        bars.fetch_bars(Settings(), "SPY")


def test_yahoo_news_is_skipped_without_request(monkeypatch):
    from options_radar import catalysts, live_scanners

    for module in (catalysts, live_scanners):
        monkeypatch.setattr(module.yf, "Ticker", _no_request)
    for cls in (catalysts.CatalystScanner, live_scanners.ResilientCatalystScanner):
        assert cls._yahoo_news_events(object.__new__(cls), ["AAPL"]) == []


def test_nasdaq_movers_and_screener_refuse_before_any_request(monkeypatch):
    monkeypatch.setattr(universe.requests, "get", _no_request)
    assert universe.nasdaq_mover_symbols() == []
    from scripts import fast_explosion_scan

    monkeypatch.setattr(fast_explosion_scan.requests, "get", _no_request)
    with pytest.raises(sp.SourceTermsBlocked):
        fast_explosion_scan._nasdaq_rows()


def test_public_chart_files_are_replaced_by_blocked_reports(monkeypatch, tmp_path):
    from scripts import build_stock_watch_charts as charts

    out, liquidity = tmp_path / "charts.json", tmp_path / "liquidity.json"
    out.write_text(json.dumps({"symbols": {"AAPL": {"intervals": {"1d": [[1, 2, 3, 4, 5]]}}}}))
    monkeypatch.setattr(charts, "collect", _no_request)
    monkeypatch.setattr(sys, "argv", ["x", "--output", str(out), "--liquidity-output", str(liquidity)])
    assert charts.main() == 0
    for path, schema in ((out, "ghazi.stock_charts.v1"), (liquidity, "ghazi.liquidity_map.v1")):
        report = json.loads(path.read_text())
        assert report["status"] == "SOURCE_TERMS_BLOCKED" and report["schema"] == schema
        assert report["symbols"] == {} and "Yahoo" in report["source"]
        datetime.fromisoformat(report["generated_at"]).astimezone(timezone.utc)


def test_index_context_and_charts_are_replaced_by_blocked_reports(monkeypatch, tmp_path):
    from scripts import build_index_context as ctx

    out, chart = tmp_path / "index_radar.json", tmp_path / "index_charts.json"
    monkeypatch.setattr(ctx, "fetch_frames", _no_request)
    monkeypatch.setattr(sys, "argv", ["x", "--output", str(out), "--charts-output", str(chart)])
    assert ctx.main() == 0
    assert json.loads(out.read_text())["status"] == "SOURCE_TERMS_BLOCKED"
    assert json.loads(chart.read_text())["schema"] == "ghazi.index_charts.v1"


TRANSPORT = re.compile(r"\byf\.(download|Ticker)\(|from yahooquery import|provider\.Ticker\(")
NASDAQ = re.compile(r"https://api\.nasdaq\.com/")


@pytest.mark.parametrize("folder", ["options_radar", "scripts"])
def test_every_yahoo_or_nasdaq_caller_checks_its_gate(folder):
    missing = []
    for path in sorted((ROOT / folder).rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if TRANSPORT.search(text) and not re.search(r"(require|allowed)\(\"yahoo\"\)", text):
            missing.append(f"{path.name}: yahoo")
        if NASDAQ.search(text) and not re.search(r"(require|allowed)\(\"nasdaq_web\"\)", text):
            missing.append(f"{path.name}: nasdaq_web")
    assert not missing, missing
