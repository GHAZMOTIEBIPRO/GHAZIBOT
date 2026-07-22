from __future__ import annotations

import json
from pathlib import Path

from options_radar.live_scanners import ResilientCatalystScanner
from options_radar.settings import Settings


def test_company_alias_match_without_sec_network(tmp_path: Path) -> None:
    aliases = tmp_path / "aliases.json"
    aliases.write_text(
        json.dumps({"NVDA": "NVIDIA Corporation", "MRNA": "Moderna Inc"}),
        encoding="utf-8",
    )
    scanner = ResilientCatalystScanner(Settings(), aliases_path=aliases)
    symbol, confidence = scanner._match_symbol(
        "NVIDIA Corporation Current Report",
        {"NVDA", "MRNA"},
    )
    assert symbol == "NVDA"
    assert confidence > 0.4
    assert "Host" not in scanner.session.headers
    assert "@" in scanner.session.headers["User-Agent"]
