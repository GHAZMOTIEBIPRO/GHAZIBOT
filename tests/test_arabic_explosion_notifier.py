from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from options_radar.arabic_explosion_notifier import build_candidates, format_candidate_message


class ArabicExplosionNotifierTests(unittest.TestCase):
    def _payload(self):
        return {
            "stocks": [
                {
                    "symbol": "TEST",
                    "price": 10.5,
                    "performance_day": 5.2,
                    "relative_volume": 3.1,
                    "float_shares": 5_000_000,
                    "avg_dollar_volume": 8_000_000,
                    "volume": 4_000_000,
                }
            ],
            "omega": {
                "opportunities": [
                    {
                        "symbol": "TEST",
                        "direction": "UPSIDE",
                        "opportunity_tier": "A",
                        "explosion_rank": 84,
                        "dimensions": {
                            "participation": 82,
                            "supply_structure": 88,
                            "options_structure": 72,
                        },
                        "catalyst": {},
                        "target_map": {
                            "entry": {"high": 10.8},
                            "invalidation": {"price": 9.9},
                        },
                    }
                ],
                "catalyst_intelligence": {
                    "by_symbol": {
                        "TEST": {
                            "headline": "FDA grants approval for the lead product",
                            "primary_source": "FDA",
                            "primary_url": "https://example.com/fda",
                            "catalyst_quality": 95,
                            "materiality": 92,
                            "confidence": 0.95,
                            "directional_bias": "bullish",
                            "reaction_state": "REPRICING",
                            "dilution_risk": 15,
                        }
                    }
                },
            },
        }

    def _fast(self):
        return {
            "actionable": [
                {
                    "symbol": "TEST",
                    "price": 10.5,
                    "move_pct": 5.2,
                    "volume": 4_000_000,
                    "turnover_pct": 2.2,
                    "score": 87,
                    "stage": "IGNITION",
                    "supply_score": 90,
                    "reasons": ["Fast Delta +5.0", "عرض مقيد 90/100"],
                }
            ],
            "halts": [],
        }

    def _delta(self):
        return {
            "top_pressure": [
                {
                    "symbol": "TEST",
                    "score": 81,
                    "stage": "PRE_EXPLOSION",
                    "supply_vacuum_score": 91,
                    "effective_float": 4_500_000,
                    "reasons": ["RVOL يتسارع 1.40→3.10", "Price Lag"],
                }
            ]
        }

    @patch.dict(os.environ, {"OMEGA_ARABIC_MIN_SCORE": "72"}, clear=False)
    def test_message_is_arabic_and_explains_causes(self):
        candidates = build_candidates(self._payload(), self._fast(), self._delta())
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.symbol, "TEST")
        self.assertEqual(candidate.stage, "IGNITION")
        self.assertIn("خبر جوهري", candidate.primary_cause)
        message = format_candidate_message(candidate)
        self.assertIn("المسبب الأقوى", message)
        self.assertIn("مسببات الانفجار المرصودة", message)
        self.assertIn("ما يؤكد استمرار الحركة", message)
        self.assertIn("الأسهم الحرة", message)
        self.assertNotIn("Pre-Explosion:", message)
        self.assertNotIn("Fast Score:", message)

    @patch.dict(os.environ, {"OMEGA_ARABIC_MAX_CHASE_PCT": "35"}, clear=False)
    def test_rejects_extended_chasing(self):
        payload = self._payload()
        payload["stocks"][0]["performance_day"] = 48
        fast = self._fast()
        fast["actionable"][0]["move_pct"] = 48
        fast["actionable"][0]["stage"] = "EXTENDED"
        candidates = build_candidates(payload, fast, self._delta())
        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
