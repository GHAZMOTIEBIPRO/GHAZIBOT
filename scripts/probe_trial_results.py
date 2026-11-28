"""Print the interpretation of posted ClinicalTrials.gov results for given NCT ids (public registry data).

ClinicalTrials.gov data is a U.S. Government (NLM) resource; the repository's registry builder already
reads its API on the runner. Usage: python -m scripts.probe_trial_results NCT05136677 [...]
"""
from __future__ import annotations

import json
import sys
import urllib.request

from options_radar.trial_results import interpret

API = "https://clinicaltrials.gov/api/v2/studies/{}"


def main(ids: list[str]) -> int:
    for nct in ids:
        req = urllib.request.Request(API.format(nct), headers={"User-Agent": "GHAZI-RADAR registry probe"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # fixed https host
                study = json.loads(r.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            print(nct, "FETCH_FAILED", type(exc).__name__)
            continue
        print("Trial results:", json.dumps(interpret(study), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["NCT05136677"]))
