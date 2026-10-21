"""bot-state publishers retry long enough to survive the burst after a push to main.

A push to main starts many publishers at once; with three retries one
second apart, GHAZI SPX Dashboard lost the race twice in a row (runs
39523481243 and 39524627272: "rejected ... fetch first").
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
STANDARD = "git pull --rebase origin bot-state && git push origin HEAD:bot-state"


def _steps():
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in (workflow.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                yield path.name, job, step


def test_standard_publish_loops_retry_eight_times_with_jitter():
    checked = 0
    for name, job, step in _steps():
        run = str(step.get("run") or "")
        if STANDARD not in run:
            continue
        checked += 1
        loop = re.search(r"for \w+ in ([0-9 ]+); do", run)
        assert loop and len(loop.group(1).split()) >= 8, f"{name}: {step.get('name')}"
        assert "RANDOM" in run, f"{name}: retries must be jittered"
        shell = step.get("shell") or (job.get("defaults") or {}).get("run", {}).get("shell") or "bash"
        assert shell == "bash", f"{name}: RANDOM needs bash"
    assert checked >= 17
