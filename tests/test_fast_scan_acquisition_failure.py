import json

import pytest
import yaml

from options_radar.source_permissions import SourceTermsBlocked
from scripts import fast_explosion_scan as scan


@pytest.mark.parametrize('failure,status', [
    (SourceTermsBlocked('nasdaq_web'), 'SOURCE_TERMS_BLOCKED'),
    (TimeoutError('https://provider.invalid/?key=SECRET'), 'MARKET_FETCH_FAILED'),
    (None, 'MARKET_FETCH_FAILED'),
])
def test_failed_acquisition_replaces_stale_candidates_and_never_alerts(
    monkeypatch, tmp_path, capsys, failure, status,
):
    output = tmp_path / 'scan.json'
    output.write_text(json.dumps({'top': [{'symbol': 'OLD'}], 'actionable': [{'symbol': 'OLD'}]}))
    monkeypatch.setattr(scan, 'OUTPUT_PATH', output)
    monkeypatch.setattr(scan, '_structural_map', dict)

    def fetch():
        if failure:
            raise failure
        return []

    monkeypatch.setattr(scan, '_nasdaq_rows', fetch)
    for name in ('collect_fast_news', 'rank_market', 'fetch_nasdaq_halts', '_send'):
        monkeypatch.setattr(scan, name, lambda *a, **k: pytest.fail('downstream work after failed acquisition'))
    assert scan.run(send_telegram=True) == 2
    report = json.loads(output.read_text())
    assert report['status'] == status
    assert report['available'] is False
    assert report['provider_quote_timestamp'] is None
    assert report['execution_authority'] is False
    assert report['market_rows_seen'] == 0
    assert report['top'] == report['actionable'] == report['halts'] == []
    assert 'SECRET' not in output.read_text() + capsys.readouterr().out


def test_failed_scan_retains_diagnostics_without_dispatching_dependents():
    from pathlib import Path

    workflow = yaml.safe_load(Path('.github/workflows/fast-explosion-radar.yml').read_text())
    steps = workflow['jobs']['scan']['steps']
    upload = next(s for s in steps if s.get('uses', '').startswith('actions/upload-artifact'))
    dispatch = next(s for s in steps if s.get('name', '').startswith('Dispatch dependent'))
    assert 'always()' in upload['if']
    assert 'always()' not in dispatch['if']
    assert not any(s.get('continue-on-error') for s in steps)
