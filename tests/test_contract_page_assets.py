"""Run dependency-free public contract page regressions in CI."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_contract_page_node_syntax_and_dom_states():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for browser JavaScript regression test")
    files = (ROOT / "public" / "contract.js", ROOT / "tests" / "contract_page_dom.test.cjs")
    for script in files:
        subprocess.run([node, "--check", str(script)], cwd=ROOT, check=True, timeout=15)
    subprocess.run([node, str(files[1])], cwd=ROOT, check=True, timeout=20)
