"""Closed gates for OCC, NasdaqTrader, the FINRA API and FRED stop every request."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from options_radar import (
    halt_news_engine,
    macro,
    occ_free_context,
    occ_free_data,
    optionable_universe,
    phase61_finra,
    phase61_intelligence,
    source_permissions,
    universe,
)
from options_radar.source_permissions import SourceTermsBlocked

ROOT = Path(__file__).resolve().parents[1]
NEW_GATES = ("occ_market_data", "nasdaqtrader", "finra_api", "fred", "bls")


class NoNetwork:
    """Session stand-in that fails the test on any request."""

    def __init__(self) -> None:
        self.headers: dict = {}

    def get(self, *args, **kwargs):
        raise AssertionError(f"request sent with the gate closed: {args[:1]}")

    post = get

    def mount(self, *args, **kwargs):
        return None


@pytest.fixture(autouse=True)
def _gates_closed(monkeypatch):
    for name in NEW_GATES:
        monkeypatch.delenv(source_permissions.GATES[name]["variable"], raising=False)
    monkeypatch.setattr("requests.get", NoNetwork().get)
    monkeypatch.setattr("requests.post", NoNetwork().get)


def test_gates_are_registered_closed_with_reasons():
    status = source_permissions.gate_status()
    for name in NEW_GATES:
        assert status[name]["allowed"] is False
        assert status[name]["status"] == "SOURCE_TERMS_BLOCKED"
        assert status[name]["reason"] and status[name]["reason_ar"]


def test_occ_clients_return_blocked_without_requests():
    result = occ_free_context.OccDailyVolumeClient(session=NoNetwork()).fetch("AAPL")
    assert result["success"] is False and result["error"] == "SOURCE_TERMS_BLOCKED"
    client = occ_free_data.OccFreeVolumeClient.__new__(occ_free_data.OccFreeVolumeClient)
    client._report_circuits = {}
    report = client.fetch_report("AAPL", "daily")
    assert report["success"] is False and report["source_block"]["status"] == "SOURCE_TERMS_BLOCKED"


def test_optionable_universe_withholds_occ_and_its_cache(tmp_path):
    cache = tmp_path / "occ_cache.json"
    cache.write_text('{"symbols": ["AAPL"], "rows": [], "product_types": ["EU"]}')
    builder = optionable_universe.IndependentOptionableUniverse(session=NoNetwork(), cache_path=cache)
    symbols, rows, types, errors, used_cache = builder.fetch_official()
    assert (symbols, rows, types, used_cache) == ([], [], [], False)
    assert errors == {"occ": "SOURCE_TERMS_BLOCKED"}


def test_free_options_script_skips_occ():
    from scripts import build_free_options_sources as script

    assert script._occ_text(NoNetwork(), script.OCC, {}) == (None, "SOURCE_TERMS_BLOCKED")


def test_nasdaqtrader_halts_and_symbol_directory_are_blocked():
    with pytest.raises(SourceTermsBlocked):
        halt_news_engine.fetch_nasdaq_halts()
    assert universe._nasdaq_trader_symbols() == []


def test_finra_reg_sho_is_blocked_in_both_collectors():
    settings = SimpleNamespace(request_timeout_seconds=5)
    for module in (phase61_intelligence, phase61_finra):
        collector = next(getattr(module, n) for n in dir(module) if n.endswith("collect_finra")
                         or n == "collect_reg_sho" or n.startswith("_collect_finra"))
        output, audit = collector(NoNetwork(), settings, ["AAPL"])
        assert output == {} and audit["error"] == "SOURCE_TERMS_BLOCKED"


def test_fred_is_blocked_even_with_a_key():
    settings = SimpleNamespace(fred_api_key="present")
    assert macro.fetch_fred_latest(settings, "DGS10") == {}


def test_every_caller_of_these_hosts_checks_a_gate():
    hosts = re.compile(r"marketdata\.theocc\.com|nasdaqtrader\.com/(dynamic|rss)|api\.finra\.org|api\.stlouisfed\.org")
    for path in [*ROOT.glob("options_radar/*.py"), *ROOT.glob("scripts/*.py")]:
        if path.name in {"probe_terms.py", "free_data_health.py", "source_permissions.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        if hosts.search(text):
            assert re.search(r"allowed\(\"(occ_market_data|nasdaqtrader|finra_api|fred)\"\)|"
                             r"require\(\"(occ_market_data|nasdaqtrader|finra_api|fred)\"\)", text), path.name


def test_bls_calendar_and_macro_context_are_withheld(tmp_path, monkeypatch):
    import json
    import sys

    from options_radar import free_public_intelligence as fpi
    from scripts import bls_macro_context

    with pytest.raises(SourceTermsBlocked):
        fpi.bls_upcoming(session=NoNetwork())
    out = tmp_path / "bls_macro.json"
    out.write_text('{"indicators": {"cpi_yoy_pct": {"value": 3.1}}}')
    monkeypatch.setattr(bls_macro_context, "fetch_bls_json", NoNetwork().get)
    monkeypatch.setattr(sys, "argv", ["x", "--output", str(out)])
    assert bls_macro_context.main() == 0
    report = json.loads(out.read_text())
    assert report["status"] == "SOURCE_TERMS_BLOCKED" and "indicators" not in report
