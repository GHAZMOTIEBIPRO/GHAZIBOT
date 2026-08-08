from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from options_radar.telegram_notifier import (
    select_alert_candidates,
    select_candidates,
    select_news_shock_candidates,
    select_price_explosion_candidates,
)


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
                    "setup_side": "call",
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
                ],
                "catalyst_intelligence": {"by_symbol": {}},
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

    @patch.dict(os.environ, {
        "TELEGRAM_MIN_NEWS_QUALITY": "80",
        "TELEGRAM_MIN_NEWS_MATERIALITY": "75",
        "TELEGRAM_MIN_NEWS_SOURCE_STRENGTH": "75",
        "TELEGRAM_NEWS_MAX_AGE_DAYS": "3",
        "TELEGRAM_MAX_DILUTION_RISK": "60",
    }, clear=False)
    def test_news_shock_does_not_require_options(self):
        payload = self._payload()
        payload["omega"]["opportunities"] = []
        payload["omega"]["catalyst_intelligence"]["by_symbol"] = {
            "TEST": {
                "symbol": "TEST",
                "headline": "Company reports material FDA approval",
                "directional_bias": "bullish",
                "event_date": datetime.now(timezone.utc).date().isoformat(),
                "primary_source": "SEC EDGAR / FDA",
                "primary_url": "https://www.sec.gov/Archives/example",
                "catalyst_quality": 91.0,
                "materiality": 95.0,
                "dilution_risk": 10.0,
                "reaction_state": "NOT_YET_REPRICED",
                "why_it_may_move": ["FDA approval"],
                "why_it_may_fail": ["Execution risk"],
            }
        }
        selected = select_news_shock_candidates(payload)
        self.assertEqual([row.symbol for row in selected], ["TEST"])
        self.assertEqual(selected[0].alert_type, "NEWS_SHOCK")

    @patch.dict(os.environ, {
        "TELEGRAM_MIN_PRICE_MOVE_PCT": "5",
        "TELEGRAM_MAX_PRICE_MOVE_PCT": "28",
        "TELEGRAM_MIN_PRICE_RVOL": "1.8",
        "TELEGRAM_MIN_PRICE_STOCK_SCORE": "70",
        "TELEGRAM_MIN_DOLLAR_VOLUME": "3000000",
    }, clear=False)
    def test_selects_early_price_volume_explosion_without_news(self):
        payload = self._payload()
        payload["omega"]["opportunities"] = []
        stock = payload["stocks"][0]
        stock.update({
            "performance_day": 9.0,
            "performance_week": 13.0,
            "performance_month": 20.0,
            "relative_volume": 2.6,
            "avg_dollar_volume": 12_000_000,
            "score": 78.0,
            "gap_pct": 2.0,
            "distance_to_trigger_atr": 0.9,
            "entry_state": "early",
            "setup_side": "call",
        })
        selected = select_price_explosion_candidates(payload)
        self.assertEqual([row.symbol for row in selected], ["TEST"])
        self.assertEqual(selected[0].alert_type, "PRICE_EXPLOSION")

    @patch.dict(os.environ, {
        "TELEGRAM_MIN_PRICE_MOVE_PCT": "5",
        "TELEGRAM_MAX_PRICE_MOVE_PCT": "28",
        "TELEGRAM_MIN_PRICE_RVOL": "1.8",
        "TELEGRAM_MIN_DOLLAR_VOLUME": "3000000",
    }, clear=False)
    def test_price_explosion_rejects_already_extended_move(self):
        payload = self._payload()
        stock = payload["stocks"][0]
        stock.update({
            "performance_day": 42.0,
            "relative_volume": 5.0,
            "avg_dollar_volume": 50_000_000,
            "score": 90.0,
        })
        self.assertEqual(select_price_explosion_candidates(payload), [])

    @patch.dict(os.environ, {"TELEGRAM_MAX_ALERTS_PER_RUN": "3"}, clear=False)
    def test_news_path_wins_same_symbol_deduplication(self):
        payload = self._payload()
        stock = payload["stocks"][0]
        stock.update({
            "performance_day": 8.0,
            "relative_volume": 2.5,
            "avg_dollar_volume": 10_000_000,
            "score": 80.0,
        })
        payload["omega"]["catalyst_intelligence"]["by_symbol"] = {
            "TEST": {
                "symbol": "TEST",
                "headline": "Material definitive agreement",
                "directional_bias": "bullish",
                "event_date": datetime.now(timezone.utc).date().isoformat(),
                "primary_source": "SEC EDGAR",
                "primary_url": "https://www.sec.gov/Archives/example",
                "catalyst_quality": 90.0,
                "materiality": 88.0,
                "dilution_risk": 5.0,
                "reaction_state": "REPRICING",
                "why_it_may_move": ["Material agreement"],
                "why_it_may_fail": [],
            }
        }
        selected = select_alert_candidates(payload)
        self.assertEqual(len([row for row in selected if row.symbol == "TEST"]), 1)
        self.assertEqual(selected[0].alert_type, "NEWS_SHOCK")


if __name__ == "__main__":
    unittest.main()
