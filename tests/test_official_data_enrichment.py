from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from options_radar.macro import fetch_treasury_curve
from options_radar.sec_fundamentals import _latest_metric, _ticker_to_cik, yahoo_fundamentals
from run_live_export import _correct_path_metrics, _fundamental_reason


def test_sec_latest_metric_uses_prior_matching_fiscal_period():
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"val": 100, "end": "2025-03-31", "filed": "2025-05-01", "form": "10-Q", "fy": 2025, "fp": "Q1"},
                            {"val": 125, "end": "2026-03-31", "filed": "2026-05-01", "form": "10-Q", "fy": 2026, "fp": "Q1"},
                        ]
                    }
                }
            }
        }
    }
    value, growth, period = _latest_metric(payload, ("Revenues",), ("USD",))
    assert value == 125
    assert growth == 0.25
    assert period == "10-Q 2026-03-31"


def test_sec_ticker_map_uses_local_fallback_when_live_endpoint_is_blocked(tmp_path, monkeypatch):
    mapping = tmp_path / "sec_cik_map.json"
    mapping.write_text(json.dumps({"AAPL": "320193", "NVDA": "1045810"}), encoding="utf-8")
    monkeypatch.setattr("options_radar.sec_fundamentals.LOCAL_CIK_MAP", mapping)

    def blocked(*args, **kwargs):
        raise RuntimeError("403 forbidden")

    monkeypatch.setattr("options_radar.sec_fundamentals.requests.get", blocked)
    result = _ticker_to_cik(SimpleNamespace(sec_user_agent="test@example.com"))
    assert result["AAPL"] == "0000320193"
    assert result["NVDA"] == "0001045810"


def test_yahoo_statement_fallback_labels_source_and_calculates_growth(monkeypatch):
    columns = pd.to_datetime([
        "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31"
    ])
    income = pd.DataFrame(
        [
            [125, 120, 115, 110, 100],
            [25, 24, 23, 22, 20],
            [1.25, 1.20, 1.15, 1.10, 1.00],
        ],
        index=["Total Revenue", "Net Income", "Diluted EPS"],
        columns=columns,
    )
    balance = pd.DataFrame(
        [[50, 49, 48, 47, 45], [300, 295, 290, 285, 280], [120, 119, 118, 117, 115]],
        index=["Cash And Cash Equivalents", "Total Assets", "Total Liabilities"],
        columns=columns,
    )
    cashflow = pd.DataFrame(
        [[40, 38, 36, 34, 32]],
        index=["Operating Cash Flow"],
        columns=columns,
    )

    class Ticker:
        quarterly_income_stmt = income
        quarterly_balance_sheet = balance
        quarterly_cashflow = cashflow

    monkeypatch.setattr("options_radar.sec_fundamentals.yf.Ticker", lambda symbol: Ticker())
    result = yahoo_fundamentals("TEST", sec_error="403")
    assert result["fundamental_source"] == "Yahoo/yfinance statements"
    assert result["fundamental_confidence"] == 0.45
    assert result["revenue"] == 125
    assert result["revenue_growth"] == 0.25
    assert result["net_margin"] == 0.2


def test_fundamental_reason_identifies_unofficial_source_and_filters_outlier_margin():
    reason = _fundamental_reason({
        "fundamental_source": "Yahoo/yfinance statements",
        "fundamental_confidence": 0.45,
        "revenue_growth": 0.25,
        "net_margin": 0.94,
        "operating_cash_flow_growth": 0.40,
    })
    assert "Yahoo غير الرسمي" in reason
    assert "SEC" not in reason
    assert "نمو الإيرادات +25.0%" in reason
    assert "هامش صافي" not in reason
    assert "ثقة 45%" in reason


def test_treasury_curve_parses_latest_row_and_slope(monkeypatch):
    xml = b'''<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
      <entry><content type="application/xml"><m:properties>
        <d:NEW_DATE>2026-07-23T00:00:00</d:NEW_DATE>
        <d:BC_3MONTH>3.60</d:BC_3MONTH><d:BC_2YEAR>3.80</d:BC_2YEAR>
        <d:BC_10YEAR>4.30</d:BC_10YEAR><d:BC_30YEAR>4.90</d:BC_30YEAR>
      </m:properties></content></entry>
      <entry><content type="application/xml"><m:properties>
        <d:NEW_DATE>2026-07-24T00:00:00</d:NEW_DATE>
        <d:BC_3MONTH>3.55</d:BC_3MONTH><d:BC_2YEAR>3.75</d:BC_2YEAR>
        <d:BC_10YEAR>4.35</d:BC_10YEAR><d:BC_30YEAR>4.95</d:BC_30YEAR>
      </m:properties></content></entry>
    </feed>'''

    class Response:
        content = xml
        def raise_for_status(self):
            return None

    monkeypatch.setattr("options_radar.macro.requests.get", lambda *args, **kwargs: Response())
    result = fetch_treasury_curve()
    assert result["date"] == "2026-07-24T00:00:00"
    assert result["treasury_10y"] == 4.35
    assert result["curve_10y_2y"] == 0.6
    assert result["curve_state"] == "normal"


def test_legacy_path_records_without_underlying_levels_are_excluded(tmp_path):
    outcomes = tmp_path / "outcomes.json"
    outcomes.write_text(
        json.dumps({
            "signals": {
                "legacy": {"path_status": "evaluated", "outcome_order": "open"},
                "valid": {
                    "path_status": "evaluated",
                    "outcome_order": "target_1_first",
                    "underlying_target_1": 105,
                    "underlying_invalidation": 95,
                },
            }
        }),
        encoding="utf-8",
    )
    payload = {"performance": {"path_evaluated": 2}}
    _correct_path_metrics(payload, SimpleNamespace(outcome_path=outcomes))
    assert payload["performance"]["path_evaluated"] == 1
    assert payload["performance"]["path_target_1_first"] == 1
    assert payload["performance"]["legacy_paths_excluded"] == 1
    persisted = json.loads(outcomes.read_text(encoding="utf-8"))
    assert persisted["signals"]["legacy"]["path_status"] == "missing_levels"
