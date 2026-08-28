from __future__ import annotations

from pathlib import Path


WORKFLOWS = Path('.github/workflows')
_CONTROL_ONLY = {'done', 'fi', 'esac', '}', ';;'}


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(' '))


def _run_blocks(lines: list[str]) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped not in {'run: |', 'run: >-', 'run: >'}:
            continue
        base = _indent(line)
        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            if candidate.strip() and _indent(candidate) <= base:
                break
            end += 1
        blocks.append((index + 1, end))
    return blocks


def test_no_terminal_unprotected_optional_copy_shortcuts() -> None:
    """Prevent the Bash pattern that caused false GitHub Action failures.

    `[[ optional-file ]] && cp ...` is safe when a later substantive command makes
    the step end with status 0. It is unsafe when it is effectively the terminal
    command (possibly followed only by `done`/`fi`), because a missing optional
    file leaves the whole GitHub Actions step with exit code 1.
    """
    offenders: list[str] = []
    for path in sorted(WORKFLOWS.glob('*.yml')):
        lines = path.read_text(encoding='utf-8').splitlines()
        for start, end in _run_blocks(lines):
            block = lines[start:end]
            for offset, line in enumerate(block):
                stripped = line.strip()
                if not (stripped.startswith('[[') and ']] && cp ' in stripped and '|| true' not in stripped):
                    continue
                later = []
                for candidate in block[offset + 1 :]:
                    text = candidate.strip()
                    if not text or text.startswith('#') or text in _CONTROL_ONLY:
                        continue
                    later.append(text)
                if not later:
                    offenders.append(f'{path}:{start + offset + 1}: {stripped}')
    assert not offenders, 'Terminal unsafe optional copy pattern(s):\n' + '\n'.join(offenders)


def test_company_news_workflow_has_no_sniper_legacy_bridge() -> None:
    path = WORKFLOWS / 'company-news-watch.yml'
    text = path.read_text(encoding='utf-8')
    assert 'sniper-news-watch.yml' not in text
    assert 'sniper-news-state' not in text
    assert 'sniper_news_alert_state' not in text
