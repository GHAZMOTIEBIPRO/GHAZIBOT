"""Every workflow job that runs code importing the options_radar package installs its runtime requirements.

options_radar/__init__.py imports pandas (and installs data normalizers), so `import options_radar.x`
fails in a job that installed only `requests`. This broke the FDA, catalyst and ops-digest Telegram
senders on 2026-11-18 (#442 made them import options_radar.telegram_ar) and the first public-archive
run on 2026-11-19; the unit tests passed because CI installs everything.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_IMPORT = re.compile(r"^\s*(from options_radar[\s.]|import options_radar\b)", re.MULTILINE)
SCRIPT_IMPORT = re.compile(r"^\s*(?:from scripts(?:\.(\w+))? import ([\w, ]+)|import scripts\.(\w+))", re.MULTILINE)
RUN_SCRIPT = re.compile(r"python3?\s+(?:-[A-Za-z]\s+)*(?:\"?[\w./$-]*?)scripts/(\w+)\.py")
RUN_MODULE = re.compile(r"python3?\s+(?:-[A-Za-z]\s+)*-m\s+(scripts|options_radar)\.(\w+)")


def _requirements_closure(name: str, seen: set[str] | None = None) -> set[str]:
    seen = set() if seen is None else seen
    path = ROOT / name
    if name in seen or not path.exists():
        return seen
    seen.add(name)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("-r "):
            _requirements_closure(line.split(None, 1)[1].strip(), seen)
    return seen


def _imports_package(script: str, seen: set[str] | None = None) -> bool:
    """True if scripts/<script>.py (or a scripts module it imports) imports options_radar."""
    seen = set() if seen is None else seen
    if script in seen:
        return False
    seen.add(script)
    path = ROOT / "scripts" / f"{script}.py"
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if PACKAGE_IMPORT.search(text):
        return True
    for module, names, plain in SCRIPT_IMPORT.findall(text):
        targets = [plain] if plain else [module] if module else [n.strip() for n in names.split(",")]
        if any(_imports_package(t, seen) for t in targets if t):
            return True
    return False


def _job_needs_and_installs(job: dict) -> tuple[list[str], bool]:
    needs: list[str] = []
    installs_runtime = False
    for step in job.get("steps") or []:
        run = str(step.get("run") or "")
        for req in re.findall(r"-r\s+[\"']?([\w./-]*requirements[\w.-]*\.txt)", run):
            if "requirements.txt" in _requirements_closure(Path(req).name):
                installs_runtime = True
        if "pip install -e" in run or "pip install ." in run:
            installs_runtime = True
        needs += [f"scripts/{s}.py" for s in RUN_SCRIPT.findall(run) if _imports_package(s)]
        for package, module in RUN_MODULE.findall(run):
            if package == "options_radar" or _imports_package(module):
                needs.append(f"{package}.{module}")
        if re.search(r"python3?\s+-\s*<<", run) and PACKAGE_IMPORT.search(run):
            needs.append("inline python importing options_radar")
    return needs, installs_runtime


def violations() -> list[str]:
    out = []
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, job in (spec.get("jobs") or {}).items():
            needs, installs = _job_needs_and_installs(job or {})
            if needs and not installs:
                out.append(f"{path.name}:{name}: {sorted(set(needs))}")
    return out


def test_jobs_running_package_code_install_the_runtime_requirements():
    assert violations() == []


def test_the_guard_detects_the_2026_11_18_failure_shape():
    job = {"steps": [{"run": 'pip install "requests>=2.32,<3.0"'},
                     {"run": "python app/scripts/send_ops_digest.py --state x"}]}
    needs, installs = _job_needs_and_installs(job)
    assert needs == ["scripts/send_ops_digest.py"] and installs is False
    job["steps"][0]["run"] = "pip install -r app/requirements.txt"
    assert _job_needs_and_installs(job)[1] is True
    # a requirements file that includes requirements.txt counts; the archive file alone does not
    assert "requirements.txt" in _requirements_closure("requirements-research.txt")
    assert "requirements.txt" not in _requirements_closure("requirements-archive.txt")
