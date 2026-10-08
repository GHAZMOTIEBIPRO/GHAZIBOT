from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from scripts import replay_explosion_calibration as calibration


def test_calibration_passes_target_to_replay():
    index = pd.date_range("2025-01-01", periods=40, freq="B")
    closes = np.full(40, 10.0)
    closes[32:] = 21.0
    history = pd.DataFrame({
        "Open": closes, "High": closes, "Low": closes,
        "Close": closes, "Volume": np.full(40, 10000),
    }, index=index)
    with patch.object(calibration.yf, "download", return_value=history):
        result = calibration._download_frame("TEST", "1y", target_return_pct=100)
    assert bool(result.iloc[31]["explosion_label"])
    assert pd.isna(result.iloc[-1]["future_5d_max_return_pct"])


def test_calibration_report_records_target(tmp_path: Path):
    with patch.object(calibration, "_download_frame", return_value=pd.DataFrame()):
        calibration.run(["TEST"], [], "1y", [60], tmp_path / "report.json", target_return_pct=100)
    import json
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["target_return_pct"] == 100
    assert "100%" in report["forward_label"]
    assert report["live_threshold_auto_changed"] is False
