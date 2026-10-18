from pathlib import Path


def test_market_widgets_are_official_embedded_display_only():
    html = Path("public/index.html").read_text(encoding="utf-8")
    assert 'data-tab="liveview"' in html
    assert 'id="tab-liveview"' in html
    assert "https://widgets.tradingview-widget.com/w/en/tv-ticker-tape.js" in html
    assert "https://widgets.tradingview-widget.com/w/en/tv-market-overview.js" in html
    assert "<tv-ticker-tape " in html
    assert "<tv-market-overview " in html
    assert "FOREXCOM:SPXUSD" in html
    assert "NASDAQ:QQQ" in html
    assert "CBOE:VIX" in html
    assert "بيانات هذه الأدوات تلقائيًا" in html
    assert "لا يمنح GHAZI RADAR واجهة بيانات API" in html
    assert "ghazi-tv-widgets.css" in html
