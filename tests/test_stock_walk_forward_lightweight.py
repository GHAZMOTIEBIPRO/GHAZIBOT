from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_stock_walk_forward_cli_help_works_without_site_packages() -> None:
    result = subprocess.run(
        [sys.executable, "-S", "-m", "scripts.run_stock_walk_forward", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "walk-forward" in result.stdout.lower()


def test_stock_walk_forward_runner_does_not_import_heavy_options_package() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "run_stock_walk_forward.py").read_text(encoding="utf-8")
    assert "from options_radar" not in source
    assert "import options_radar" not in source
