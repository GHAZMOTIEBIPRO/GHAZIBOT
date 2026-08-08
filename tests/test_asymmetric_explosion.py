from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from options_radar.asymmetric_explosion import select_asymmetric_candidates


class AsymmetricExplosionTests(unittest.TestCase):
    @patch.dict(os.environ, {"TELEGRAM_MIN_ASYMMETRIC_SCORE": "60"}, clear=False)
    def test_rgc_like_broken_float_without_news(self):
        payload = {
            "stocks": [
                {
                    "symbol": "VACU",
                    "price": 8.0,
                    "public_float_shares": 2_500_000,
                    "shares_outstanding": 30_000_000,
                    "insider_ownership_pct": 82,
                    "relative_volume": 2.2,
                    "performance_day": 6.0,
                    "performance_week": 10.0,
                    "avg_dollar_volume": 2_000_000,
                    "entry_state": "early",
                    "breakout": False,
                }
            ],
            "omega": {"opportunities": [], "catalyst_intelligence": {"by_symbol": {}}},
        }
        rows = select_asymmetric_candidates(payload)
        self.assertEqual(rows[0].symbol, "VACU")
        self.assertIn("RGC-LIKE", rows[0].archetype)

    @patch.dict(os.environ, {"TELEGRAM_MIN_ASYMMETRIC_SCORE": "70"}, clear=False)
    def test_bnai_like_catalyst_plus_micro_float(self):
        payload = {
            "stocks": [
                {
                    "symbol": "AIBX",
                    "price": 12.0,
                    "public_float_shares": 3_100_000,
                    "relative_volume": 2.8,
                    "performance_day": 9.0,
                    "performance_week": 14.0,
                    "avg_dollar_volume": 8_000_000,
                    "entry_state": "early",
                }
            ],
            "omega": {
                "opportunities": [],
                "catalyst_intelligence": {
                    "by_symbol": {
                        "AIBX": {
                            "headline": "AI licensing partnership signed",
                            "catalyst_quality": 90,
                            "materiality": 88,
                            "confidence": 0.9,
                            "age_days": 0,
                            "directional_bias": "bullish",
                            "reaction_state": "REPRICING",
                            "dilution_risk": 10,
                        }
                    }
                },
            },
        }
        rows = select_asymmetric_candidates(payload)
        self.assertEqual(rows[0].symbol, "AIBX")
        self.assertTrue("BNAI" in rows[0].archetype or "HYBRID" in rows[0].archetype)

    @patch.dict(os.environ, {"TELEGRAM_MIN_ASYMMETRIC_SCORE": "70"}, clear=False)
    def test_rejects_extended_chase(self):
        payload = {
            "stocks": [
                {
                    "symbol": "LATE",
                    "price": 30.0,
                    "public_float_shares": 2_000_000,
                    "relative_volume": 8.0,
                    "performance_day": 80.0,
                    "performance_week": 150.0,
                    "avg_dollar_volume": 20_000_000,
                    "entry_state": "too_late",
                }
            ],
            "omega": {"opportunities": [], "catalyst_intelligence": {"by_symbol": {}}},
        }
        self.assertEqual(select_asymmetric_candidates(payload), [])


if __name__ == "__main__":
    unittest.main()
