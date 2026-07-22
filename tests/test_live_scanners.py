from __future__ import annotations

import json
from pathlib import Path

from options_radar.live_scanners import ResilientCatalystScanner
from options_radar.settings import Settings


def _scanner(tmp_path: Path) -> ResilientCatalystScanner:
    aliases = tmp_path / "aliases.json"
    aliases.write_text(
        json.dumps(
            {
                "NVDA": "NVIDIA Corporation",
                "MRNA": "Moderna Inc",
                "AMZN": "Amazon.com Inc",
                "UBER": "Uber Technologies Inc",
            }
        ),
        encoding="utf-8",
    )
    return ResilientCatalystScanner(Settings(), aliases_path=aliases)


def test_company_alias_match_without_sec_network(tmp_path: Path) -> None:
    scanner = _scanner(tmp_path)
    symbol, confidence = scanner._match_symbol(
        "NVIDIA Corporation Current Report",
        {"NVDA", "MRNA"},
    )
    assert symbol == "NVDA"
    assert confidence > 0.3
    assert "Host" not in scanner.session.headers
    assert "@" in scanner.session.headers["User-Agent"]


def test_unrelated_quote_page_news_is_rejected(tmp_path: Path) -> None:
    scanner = _scanner(tmp_path)
    assert not scanner._news_is_relevant(
        "AMZN",
        "Alaska Air to acquire four cargo jets and base some in Hawaii",
    )
    assert scanner._news_is_relevant(
        "UBER",
        "Is Uber Technologies undervalued following its Delivery Hero deal?",
    )
