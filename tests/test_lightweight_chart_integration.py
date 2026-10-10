from pathlib import Path


def test_lightweight_charts_is_pinned_and_attributed():
    html = Path("public/index.html").read_text(encoding="utf-8")
    assert "lightweight-charts@5.2.1" in html
    assert "https://www.tradingview.com/" in html
    assert "market-chart.js" in html


def test_chart_render_keeps_research_authority_explicit():
    source = Path("public/market-chart.js").read_text(encoding="utf-8")
    assert "لا يغيّر بوابة V11" in source
    assert "createPriceLine" in source
