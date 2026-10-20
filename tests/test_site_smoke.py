import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_script_is_valid_node():
    assert subprocess.run(["node", "--check", str(ROOT / "scripts/site_smoke.cjs")]).returncode == 0


def test_smoke_workflow_pins_playwright_and_publishes_only_its_report():
    text = (ROOT / ".github/workflows/site-smoke.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert doc["permissions"] == {"contents": "write"}
    assert doc["concurrency"]["cancel-in-progress"] is False
    assert re.search(r"playwright@\d+\.\d+\.\d+", text)
    adds = re.findall(r"git add (.+)", text)
    assert adds == ["runtime/public/data/site_smoke.json"]
    assert "secrets." not in text


def test_smoke_report_feeds_the_website_scorecard():
    import importlib.util

    spec = importlib.util.spec_from_file_location("cards", ROOT / "scripts/build_platform_scorecards.py")
    cards = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cards)
    smoke = {"pages": {"a:home": {"errors": [], "overflow": False},
                       "a:spx": {"errors": ["TypeError"], "overflow": False}}}
    metric = cards.website(smoke)
    assert metric["status"] == "MEASURED" and metric["value"] == 50.0
