from __future__ import annotations

import json
from pathlib import Path


def test_vercel_uses_repository_ignore_command() -> None:
    config = json.loads(Path("vercel.json").read_text(encoding="utf-8"))
    assert config["outputDirectory"] == "public"
    assert config["ignoreCommand"] == "bash scripts/vercel-ignore-build.sh"


def test_ignore_script_skips_preview_and_backend_only_changes() -> None:
    script = Path("scripts/vercel-ignore-build.sh").read_text(encoding="utf-8")
    assert '"${VERCEL_ENV:-}" != "production"' in script
    assert "public/app.js" in script
    assert "public/index.html" in script
    assert "public/styles.css" in script
    assert "public/data/latest.json" not in script


def test_dashboard_reads_live_github_data_with_local_fallback() -> None:
    app = Path("public/app.js").read_text(encoding="utf-8")
    assert "raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/main/public/data/latest.json" in app
    assert '"./data/latest.json"' in app
    assert "fetchDataFreshnessRank" in app
    assert "for (const [position, index] of order.entries())" in app
    assert "DATA_META_URLS" in app


def test_multi_megabyte_latest_json_loads_only_with_the_detailed_dashboard():
    app = Path("public/app.js").read_text(encoding="utf-8")
    hub = Path("public/terminal-hub.js").read_text(encoding="utf-8")
    # No unconditional page-load fetch or poll of latest.json.
    assert "\nloadData(false);\nsetInterval(() => loadData(false)" not in app
    assert "window.ghaziEnsureLegacyData = ensureLegacyData;" in app
    assert "\nloadFreshnessOnly();" in app
    assert "window.ghaziEnsureLegacyData?.();" in hub
    # The light header names the status time, never the report time.
    assert "آخر تحديث لحالة البيانات" in app
