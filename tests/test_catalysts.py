from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("yfinance")

from options_radar.catalysts import _score_text, best_catalyst_map


def test_negative_financing_dominates_generic_positive_phrase() -> None:
    score, category, _ = _score_text(
        "The company announced a strategic partnership and a registered direct offering."
    )
    assert score < 0
    assert "offering" in category.lower()


def test_best_catalyst_map_applies_negative_risk_to_positive_event() -> None:
    frame = pd.DataFrame([
        {
            "symbol": "XYZ", "score": 20, "category": "FDA approval",
            "headline": "Approved", "url": "positive", "source": "SEC",
        },
        {
            "symbol": "XYZ", "score": -10, "category": "Offering",
            "headline": "Financing", "url": "negative", "source": "SEC",
        },
    ])
    result = best_catalyst_map(frame)["XYZ"]
    assert result["score"] == 10
    assert result["negative_score"] == -10
