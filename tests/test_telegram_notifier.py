from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from options_radar.telegram_notifier import select_candidates


class TelegramNotifierSelectionTests(unittest.TestCase):
    def _payload(self):
        return {
            "stocks": [
                {
                    "symbol": "TEST",
                    "price": 10.0,
                    "performance_day": 2.0,
                    "performance_week": 6.0,
                    "performance_month": 12.0,
                    "gap_pct": 1.0,
                    "distance_to_trigger_atr": 0.6,
                    "entry_state": "early",
                }
            ],
            "omega": {
                "opportunities": [
                    {
                        "symbol": "TEST",
                        "price": 10.0,
                        "direction": "UPSIDE",
                        "opportunity_tier": "A",
                        "explosion_rank": 86.0,
                        "data_fresh": True,
                        "no_trade_state": None,
                        "dimensions": {
                            "risk_penalty": 12.0,
                            "participation": 82.0,
                            "supply_structure": 74.0,
                            "options_structure": 68.0,
                        },
                        "catalyst": {
                            "dilution_risk": 20.0,
                            "reaction_state": "EARLY",
                        },
                    }
                ]
            },
        }

    @patch.dict(os.environ, {
        "TELEGRAM_MIN_EXPLOSION_RANK": "80",
        "TELEGRAM_MIN_EARLYNESS": "75",
        "TELEGRAM_MAX_DILUTION_RISK": "60",
        "TELEGRAM_MAX_RISK_PENALTY": "38",
    }, clear=False)
    def test_selects_strong_early_upside_candidate(self):
        selected = select_candidates(self._payload())
        self.assertEqual([row.symbol for row in selected], ["TEST"])
        self.assertGreaterEqual(selected[0].earlyness, 75)

    @patch.dict(os.environ, {
        "TELEGRAM_MIN_EXPLOSION_RANK": "80",
        "TELEGRAM_MIN_EARLYNESS": "75",
    }, clear=False)
    def test_rejects_extended_candidate(self):
        payload = self._payload()
        payload["stocks"][0]["performance_week"] = 85.0
        payload["stocks"][0]["entry_state"] = "too_late"
        selected = select_candidates(payload)
        self.assertEqual(selected, [])

    @patch.dict(os.environ, {
        "TELEGRAM_MIN_EXPLOSION_RANK": "80",
        "TELEGRAM_MIN_EARLYNESS": "75",
        "TELEGRAM_MAX_DILUTION_RISK": "60",
    }, clear=False)
    def test_rejects_high_dilution_candidate(self):
        payload = self._payload()
        payload["omega"]["opportunities"][0]["catalyst"]["dilution_risk"] = 90.0
        selected = select_candidates(payload)
        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
