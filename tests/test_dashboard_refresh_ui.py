from pathlib import Path


def test_dashboard_separates_call_and_put_contracts() -> None:
    html = Path("public/index.html").read_text(encoding="utf-8")
    javascript = Path("public/app.js").read_text(encoding="utf-8")

    assert 'id="call-options-body"' in html
    assert 'id="put-options-body"' in html
    assert 'id="call-count"' in html
    assert 'id="put-count"' in html
    assert 'option_type' in javascript
    assert 'sideLabel(option.option_type) === "CALL"' in javascript
    assert 'sideLabel(option.option_type) === "PUT"' in javascript


def test_dashboard_shows_exact_riyadh_fetch_time() -> None:
    html = Path("public/index.html").read_text(encoding="utf-8")
    javascript = Path("public/app.js").read_text(encoding="utf-8")

    assert 'id="last-updated"' in html
    assert 'id="page-loaded-at"' in html
    assert 'id="refresh-result"' in html
    assert 'Asia/Riyadh' in javascript
    assert 'وقت جلب السوق' in javascript
    assert 'لا يوجد ملف أحدث' in javascript


def test_owner_manual_refresh_marker_triggers_workflow() -> None:
    workflow = Path(".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    marker = Path("data/manual_refresh.txt")

    assert marker.exists()
    assert 'data/manual_refresh.txt' in workflow
    assert 'workflow_dispatch:' in workflow
