from __future__ import annotations

import json
from pathlib import Path

from options_radar.calibration import build_calibration_report
from options_radar.calibration_report import render_calibration_markdown


def _write_signal(path: Path, signal_id: str, score: float = 70.0) -> None:
    path.write_text(
        json.dumps(
            {
                "signal_id": signal_id,
                "score": score,
                "catalyst": "bullish EMA stack",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_same_scan_quote_does_not_unlock_calibration(tmp_path: Path) -> None:
    signals = tmp_path / "signals.jsonl"
    outcomes = tmp_path / "outcomes.json"
    _write_signal(signals, "same-scan")
    outcomes.write_text(
        json.dumps(
            {
                "signals": {
                    "same-scan": {
                        "observations": 3,
                        "mfe_pct": 4.0,
                        "mae_pct": -2.0,
                        "checkpoints": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    report = build_calibration_report(signals, outcomes, minimum_sample=1)

    assert report["raw_priced_sample"] == 1
    assert report["matured_sample"] == 0
    assert report["priced_sample"] == 0
    assert report["calibration_ready"] is False
    assert report["score_bands"][2]["observed"] == 1
    assert report["score_bands"][2]["matured"] == 0


def test_one_day_checkpoint_unlocks_calibration(tmp_path: Path) -> None:
    signals = tmp_path / "signals.jsonl"
    outcomes = tmp_path / "outcomes.json"
    _write_signal(signals, "mature")
    outcomes.write_text(
        json.dumps(
            {
                "signals": {
                    "mature": {
                        "observations": 4,
                        "mfe_pct": 7.0,
                        "mae_pct": -3.0,
                        "target_1_observed": True,
                        "checkpoints": {
                            "1d": {"price": 1.2, "return_pct": 5.0},
                            "5d": {"price": 1.3, "return_pct": 8.0},
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    report = build_calibration_report(signals, outcomes, minimum_sample=1)

    assert report["matured_sample"] == 1
    assert report["five_day_sample"] == 1
    assert report["calibration_ready"] is True
    assert report["score_bands"][2]["target_1_rate"] == 1.0


def test_markdown_distinguishes_raw_and_mature_samples() -> None:
    markdown = render_calibration_markdown(
        {
            "calibration_ready": False,
            "raw_priced_sample": 44,
            "matured_sample": 12,
            "five_day_sample": 3,
            "maturity_checkpoint": "1d",
            "minimum_sample": 100,
            "score_bands": [],
            "catalysts": [],
        },
        "2026.07-phase2",
    )

    assert "Mature signals (1d checkpoint):** **12/100" in markdown
    assert "Raw priced signals:** **44" in markdown
    assert "Same-scan observations do not count" in markdown
