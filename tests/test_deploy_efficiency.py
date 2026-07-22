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
    assert "for (const url of DATA_URLS)" in app
