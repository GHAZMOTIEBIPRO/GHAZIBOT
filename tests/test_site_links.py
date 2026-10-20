from options_radar.site_links import chart_link_html, chart_url
from scripts.send_independent_path_alerts import _option_message, _stock_message


def test_chart_url_validates_symbol():
    assert chart_url("rgc") == "https://ghazibot.vercel.app/?chart=RGC"
    assert chart_url("BRK.B") == "https://ghazibot.vercel.app/?chart=BRK.B"
    for bad in ("", None, '"><script>', "1ABC", "TOOLONGSYMBOL1"):
        assert chart_url(bad) is None
        assert chart_link_html(bad) == ""


def test_stock_and_option_alerts_link_to_the_site_chart():
    stock = _stock_message({"symbol": "RGC", "score": 71, "price": 3.2, "move_pct": 12.0,
                            "stage": "PRESSURE_BUILDING"})
    assert '<a href="https://ghazibot.vercel.app/?chart=RGC">' in stock
    option = _option_message({"symbol": "NVDA", "option_type": "CALL", "strike": 200,
                              "expiration": "2026-10-23", "dte": 3})
    assert '<a href="https://ghazibot.vercel.app/?chart=NVDA">' in option
    assert "<a href" not in _stock_message({"symbol": "<b>", "stage": "WATCH"})
