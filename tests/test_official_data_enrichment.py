from __future__ import annotations

from types import SimpleNamespace

from options_radar.macro import fetch_treasury_curve
from options_radar.sec_fundamentals import _latest_metric


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
