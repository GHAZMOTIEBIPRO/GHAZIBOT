import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_script_is_valid_node():
    assert subprocess.run(["node", "--check", str(ROOT / "scripts/site_smoke.cjs")], check=False).returncode == 0


def test_every_smoke_page_is_checked_against_this_checkouts_script_versions():
    text = (ROOT / "scripts/site_smoke.cjs").read_text(encoding="utf-8")
    labels = re.findall(r'\["(\w+)", "/', text.split("const PAGES", 1)[1].split(";", 1)[0])
    files = dict(re.findall(r'(\w+): "(public/[^"]+\.html)"', text.split("const PAGE_FILES", 1)[1].split("};", 1)[0]))
    assert labels and set(labels) == set(files)
    for label, file in files.items():
        html = (ROOT / file).read_text(encoding="utf-8")
        assert re.search(r'<script[^>]*\ssrc="[^"]*\?v=[^"]*"', html), (label, file)
    assert re.search(r"VERSION\s*=\s*[\"'][^\"']+", (ROOT / "public/sw.js").read_text(encoding="utf-8"))
    assert "production_matches_checkout" in text and "scripts_missing" in text


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


def test_validity_ignores_runs_still_in_progress():
    import importlib.util

    spec = importlib.util.spec_from_file_location("cards2", ROOT / "scripts/build_platform_scorecards.py")
    cards = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cards)
    runs = [{"id": 2, "status": "in_progress", "conclusion": None, "created_at": "2026-10-20T19:00:00Z"},
            {"id": 1, "status": "completed", "conclusion": "success", "created_at": "2026-10-20T18:00:00Z"}]
    metric = cards.validity(runs)
    assert metric["status"] == "PASSING" and metric["evidence"]["run_id"] == 1
    assert cards.validity([runs[0]])["status"] == "UNMEASURED"
