from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = Path('.github/workflows')
# Keys GitHub requires to be mappings when present. `env:` left empty after its
# entries are removed is valid YAML (null) but GitHub rejects the whole workflow,
# so every push run fails with no jobs.
_MAPPING_KEYS = {'env', 'with', 'secrets', 'outputs', 'inputs', 'defaults', 'permissions'}


def _empty_mappings(node, path: list[str], out: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _MAPPING_KEYS and value is None:
                out.append('.'.join([*path, str(key)]))
            _empty_mappings(value, [*path, str(key)], out)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _empty_mappings(value, [*path, str(index)], out)


def test_workflow_mapping_keys_are_never_empty() -> None:
    offenders: list[str] = []
    for path in sorted(WORKFLOWS.glob('*.yml')):
        found: list[str] = []
        _empty_mappings(yaml.safe_load(path.read_text(encoding='utf-8')), [], found)
        offenders.extend(f'{path.name}: {item}' for item in found)
    assert offenders == []
