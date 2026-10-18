from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "public/index.html").read_text(encoding="utf-8")
JS = (ROOT / "public/ghazi-radar-quality.js").read_text(encoding="utf-8")
APP = (ROOT / "public/app.js").read_text(encoding="utf-8")


def test_public_branding_and_quality_panel():
    assert "<title>GHAZI RADAR" in HTML
    assert "<h1>GHAZI RADAR</h1>" in HTML
    assert "ghazi-radar-quality.js" in HTML
    for element_id in (
        "ghazi-stock-sources", "ghazi-option-sources",
        "ghazi-research-chains", "ghazi-approved-contracts",
        "ghazi-option-readiness", "ghazi-flow-readiness",
        "ghazi-report-time", "ghazi-chain-providers", "ghazi-sec-status",
    ):
        assert f'id="{element_id}"' in HTML


def test_report_timestamp_never_claims_quote_freshness():
    assert "ليس وقت تسعير العقد" in APP
    assert "وقت إنشاء التقرير" in APP
    assert "وقت جلب السوق:" not in APP
    assert "generated_at" in JS
    assert "production_quote_ready" in JS
    assert "production_flow_ready" in JS


def test_fail_closed_and_no_invented_source_numbers():
    assert 'return "—"' in JS
    assert "Promise.allSettled" in JS
    assert "clearData()" in JS
    assert "active_option_sources" in JS
    assert "usable_chains" in JS
    assert "getElementById" in JS
