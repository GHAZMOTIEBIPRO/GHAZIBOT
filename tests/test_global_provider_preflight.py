from __future__ import annotations

from pathlib import Path

from options_radar.hybrid_fetcher import DataFetcher


def test_package_import_installs_provider_preflight_globally() -> None:
    assert getattr(DataFetcher, "_ghazi_provider_preflight_v1", False) is True


def test_package_init_installs_preflight_after_phase61_fetcher() -> None:
    text = (Path(__file__).resolve().parents[1] / "options_radar" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert text.index("install_phase61_fetching()") < text.index("install_provider_preflight()")
