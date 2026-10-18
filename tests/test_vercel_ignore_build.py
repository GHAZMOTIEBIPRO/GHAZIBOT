"""Regression: Vercel must deploy new frontend components, not runtime metadata."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path("scripts/vercel-ignore-build.sh").resolve()


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


@pytest.mark.parametrize(
    ("changed", "environment", "exit_code"),
    [
        ("public/index-radar.js", "production", 1),
        ("public/decision-room.js", "production", 1),
        ("public/ghazi-radar-quality.css", "production", 1),
        ("public/spx/spx.js", "production", 1),
        ("public/data/data-status.json", "production", 1),
        ("public/data/health.json", "production", 1),
        ("public/data/latest.json", "production", 0),
        ("docs/CHANGELOG.md", "production", 0),
        ("scripts/build_index_context.py", "production", 0),
        ("vercel.json", "production", 1),
        ("public/index-radar.js", "preview", 0),
    ],
)
def test_deploy_only_for_production_ui_changes(tmp_path: Path, changed: str,
                                                environment: str, exit_code: int) -> None:
    assert SCRIPT.is_file()
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    first = tmp_path / changed
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("initial", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "baseline")
    first.write_text("updated", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "test change")
    env = {**os.environ, "VERCEL_ENV": environment}
    outcome = subprocess.run(["bash", str(SCRIPT)], cwd=tmp_path, env=env,
                             text=True, capture_output=True, check=False)
    assert outcome.returncode == exit_code, (
        changed, environment, outcome.stdout, outcome.stderr
    )


def test_no_parent_commit_builds_by_default(tmp_path: Path) -> None:
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "readme.txt").write_text("one", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "initial")
    outcome = subprocess.run(
        ["bash", str(SCRIPT)], cwd=tmp_path,
        env={**os.environ, "VERCEL_ENV": "production"},
        text=True, capture_output=True, check=False,
    )
    assert outcome.returncode == 1
