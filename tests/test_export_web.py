from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from export_web import _records, _write_atomic


def test_records_are_strict_json_safe() -> None:
    frame = pd.DataFrame([
        {
            "symbol": "XYZ",
            "score": np.float64(88.5),
            "missing": np.nan,
            "expiration": pd.Timestamp("2026-08-21"),
        }
    ])
    records = _records(frame)
    encoded = json.dumps(records, allow_nan=False)
    assert '"symbol": "XYZ"' in encoded
    assert records[0]["missing"] is None
    assert records[0]["expiration"].startswith("2026-08-21")


def test_atomic_write(tmp_path: Path) -> None:
    output = tmp_path / "public" / "data" / "latest.json"
    _write_atomic(output, {"ok": True})
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
