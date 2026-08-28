from __future__ import annotations

from pathlib import Path


WORKFLOWS = Path('.github/workflows')


def test_no_unprotected_optional_copy_shortcuts() -> None:
    """Prevent the exact shell pattern that caused false GitHub Action failures.

    In bash -e workflow steps, a final `[[ ... ]] && cp ...` may return exit code 1
    when the optional source file is absent. Optional copies must use an explicit
    if/then block or otherwise neutralize the non-match.
    """
    offenders: list[str] = []
    for path in sorted(WORKFLOWS.glob('*.yml')):
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith('[[') and ']] && cp ' in stripped and '|| true' not in stripped:
                offenders.append(f'{path}:{lineno}: {stripped}')
    assert not offenders, 'Unsafe optional copy pattern(s):\n' + '\n'.join(offenders)


def test_company_news_workflow_has_no_sniper_legacy_bridge() -> None:
    path = WORKFLOWS / 'company-news-watch.yml'
    text = path.read_text(encoding='utf-8')
    assert 'sniper-news-watch.yml' not in text
    assert 'sniper-news-state' not in text
    assert 'sniper_news_alert_state' not in text
