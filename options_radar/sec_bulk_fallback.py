"""Read locally provisioned *official* SEC nightly submissions ZIP offline.

No network fetch or 403 circumvention is attempted. ZIP safety and issuer
identity are required; reporting preserves bulk-cache provenance.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any

CIK_ENTRY = re.compile(r"^CIK\d{10}\.json$")


def read_issuer(path: str | Path | None, cik: int, symbol: str) -> dict[str, Any] | None:
    if not path or type(cik) is not int or cik <= 0 or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,8}", symbol):
        return None
    file = Path(path)
    if not file.is_file() or file.suffix.lower() != ".zip":
        return None
    name = f"CIK{cik:010d}.json"
    if not CIK_ENTRY.fullmatch(name):
        return None
    try:
        with zipfile.ZipFile(file) as archive:
            info = archive.getinfo(name)
            if (info.file_size > 6_000_000 or info.compress_size > 5_000_000
                    or info.file_size / max(1, info.compress_size) > 150):
                return None
            with archive.open(info) as source:
                raw = source.read(6_000_001)
        if len(raw) > 6_000_000:
            return None
        payload = json.loads(raw)
        if not isinstance(payload, dict) or int(payload.get("cik", -1)) != cik:
            return None
        tickers = payload.get("tickers")
        if not isinstance(tickers, list) or symbol not in {
            x.strip().upper() for x in tickers if isinstance(x, str)
        }:
            return None
        if not isinstance(payload.get("filings"), dict):
            return None
        return payload
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, RuntimeError):
        return None
