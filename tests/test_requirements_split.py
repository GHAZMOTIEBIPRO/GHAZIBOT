"""Runtime installs stay lean: gated Yahoo clients and the local Streamlit UI are not runtime dependencies,
and production modules import without them (2026-11-19: 55 -> 18 packages, 514 -> 169 MB)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _names(path: Path) -> set[str]:
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-r"):
            out.add(line.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip().lower())
    return out


def test_chart_library_is_only_for_the_daily_plan():
    assert "matplotlib" not in _names(ROOT / "requirements.txt")
    assert _names(ROOT / "requirements-charts.txt") == {"matplotlib"}
    assert "requirements-charts.txt" in (ROOT / ".github/workflows/daily-plan.yml").read_text(encoding="utf-8")
    assert (ROOT / "assets/fonts/NotoSansArabic-Regular.ttf").exists() and (ROOT / "assets/fonts/OFL.txt").exists()


def test_runtime_requirements_exclude_gated_and_ui_packages():
    runtime = _names(ROOT / "requirements.txt")
    assert not runtime & {"yfinance", "yahooquery", "streamlit"}
    assert {"yfinance", "yahooquery"} <= _names(ROOT / "requirements-legacy.txt")
    assert "streamlit" in _names(ROOT / "requirements-ui.txt")
    assert "-r requirements-legacy.txt" in (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")


def test_production_modules_import_without_yahoo_or_streamlit_installed():
    code = ("import sys\n"
            "for m in ('yfinance', 'yahooquery', 'streamlit'):\n"
            "    sys.modules[m] = None\n"
            "import options_radar.market_bars, options_radar.providers, options_radar.catalysts\n"
            "import options_radar.hybrid_fetcher, options_radar.live_scanners, options_radar.sec_fundamentals\n"
            "import scripts.build_daily_plan, scripts.private_market_scan, scripts.send_news_flash_24x7\n")
    proc = subprocess.run([sys.executable, "-c", code], check=False, cwd=ROOT, capture_output=True, text=True,
                          timeout=120)
    assert proc.returncode == 0, proc.stderr[-800:]


def test_lazy_yfinance_imports_on_first_use_and_explains_a_missing_install(monkeypatch):
    from options_radar import yahoo_optional

    proxy = yahoo_optional._LazyModule("ghazi_definitely_missing_module")
    with pytest.raises(ModuleNotFoundError, match="requirements-legacy.txt"):
        proxy.download  # noqa: B018
    present = yahoo_optional._LazyModule("json")
    assert present.dumps({"a": 1}) == '{"a": 1}'
    monkeypatch.setattr(present, "dumps", lambda obj: "patched")  # tests can still stub calls
    assert present.dumps({}) == "patched"
