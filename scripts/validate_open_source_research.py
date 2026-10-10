from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from options_radar.open_source_research import build_open_source_research_snapshot


OUTPUT = Path("public/data/open_source_research_validation.json")


def _fixture_history(rows: int = 140) -> pd.DataFrame:
    index = pd.date_range("2026-01-02", periods=rows, freq="B")
    trend = np.linspace(100.0, 122.0, rows)
    wave = np.sin(np.arange(rows) / 4.0) * 2.5
    close = trend + wave
    return pd.DataFrame(
        {
            "Open": close - 0.35,
            "High": close + 1.15,
            "Low": close - 1.10,
            "Close": close,
            "Volume": 1_000_000 + (np.arange(rows) % 11) * 25_000,
        },
        index=index,
    )


def main() -> int:
    snapshot = build_open_source_research_snapshot(_fixture_history())
    smc = snapshot["smart_money_concepts"]
    edgar = snapshot["edgartools"]

    if smc.get("live_decision_authority") is not False:
        raise RuntimeError("SMC research bridge must never gain live decision authority")
    if edgar.get("live_decision_authority") is not False:
        raise RuntimeError("EdgarTools research bridge must never gain live decision authority")
    if not edgar.get("available"):
        raise RuntimeError("EdgarTools is not importable in the research environment")
    if smc.get("safe_swing_cutoff_index", -1) >= smc.get("bars", 0) - 1:
        raise RuntimeError("SMC confirmation lag was not enforced")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
