"""Read-only structural probe of OCC's free public market-data endpoints.

Prints response *shape* only: HTTP status, content type, size, line count,
and the first lines with every digit masked to ``9`` so no OI, volume, date
or strike value is published. HTML responses report only their <title> and
form field names, which document the parameters OCC actually accepts.

No credentials, no writes, no state. Bounded to a handful of requests.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

BASE = "https://marketdata.theocc.com"
MAX_BYTES = 3_000_000
SHAPE_LINES = 14
SAFE_SYMBOL = re.compile(r"^[A-Z]{1,6}$")


def _prior_weekday(today: date) -> date:
    day = today - timedelta(days=1)
    while day.weekday() > 4:
        day -= timedelta(days=1)
    return day


def _mask(cell: str) -> str:
    text = re.sub(r"\d", "9", cell.strip())
    return text[:28]


def _split(line: str) -> list[str]:
    if "\t" in line:
        return line.split("\t")
    if "," in line:
        try:
            return next(csv.reader([line]))
        except (csv.Error, StopIteration):
            return [line]
    return re.split(r"\s{2,}", line.strip())


def describe(text: str) -> dict[str, Any]:
    body = text.lstrip("﻿")
    if body.lstrip()[:1] == "<":
        title = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        names = sorted(set(re.findall(r"""name=["']([A-Za-z][\w.-]{0,40})["']""", body)))
        actions = sorted(set(re.findall(r"""action=["']([^"'#?]{0,80})""", body)))
        return {
            "kind": "HTML",
            "title": html.unescape(title.group(1)).strip()[:80] if title else None,
            "form_field_names": names[:40],
            "form_actions": actions[:10],
        }
    lines = [line for line in body.splitlines() if line.strip()]

    def shape(selected: list[str]) -> list[dict[str, Any]]:
        out = []
        for line in selected:
            cells = _split(line)
            if len(cells) == 1:
                # Single-cell title/footer lines carry report labels and
                # dates, not per-contract values; show them in full.
                out.append({"cells": 1, "title_line": line.strip()[:160]})
            else:
                out.append({"cells": len(cells),
                            "masked": [_mask(c) for c in cells[:16]]})
        return out

    return {
        "kind": "TEXT",
        "non_empty_lines": len(lines),
        "tab_lines": sum(1 for line in lines[:200] if "\t" in line),
        "comma_lines": sum(1 for line in lines[:200] if "," in line),
        "masked_shape": shape(lines[:SHAPE_LINES]),
        "tail_shape": shape(lines[-4:]) if len(lines) > SHAPE_LINES else [],
    }


def probe(session: Any, path: str, params: dict | None) -> dict[str, Any]:
    out: dict[str, Any] = {"path": path, "param_names": sorted(params or {})}
    try:
        response = session.get(
            BASE + path, params=params, timeout=20, stream=True,
            headers={"Accept": "text/csv,text/plain,text/html;q=0.8,*/*;q=0.5",
                     "User-Agent": "GHAZI-research-probe/1.0"},
        )
        out["status"] = response.status_code
        out["content_type"] = response.headers.get("Content-Type", "")[:60]
        for name in ("Content-Disposition", "Last-Modified", "Date"):
            out[name.lower().replace("-", "_")] = (
                response.headers.get(name) or "")[:120]
        chunks, size = [], 0
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_BYTES:
                out["truncated"] = True
                break
            chunks.append(chunk)
        out["bytes"] = size
        out.update(describe(b"".join(chunks).decode("utf-8", "replace")))
    except requests.RequestException as exc:
        out["error"] = type(exc).__name__
    return out


def plan(symbol: str, today: date) -> list[tuple[str, dict | None]]:
    day = _prior_weekday(today)
    slash, compact = day.strftime("%m/%d/%Y"), day.strftime("%Y%m%d")
    return [
        ("/daily-open-interest",
         {"reportDate": slash, "action": "download", "format": "csv"}),
        ("/daily-open-interest", None),
        ("/series-search", {"symbolType": "U", "symbol": symbol}),
        ("/series-search", {"symbolType": "O", "symbol": symbol}),
        ("/volume-query",
         {"reportDate": compact, "format": "csv", "volumeQueryType": "O",
          "symbolType": "U", "symbol": symbol, "reportType": "D",
          "accountType": "ALL", "productKind": "ALL", "porc": "BOTH"}),
        ("/volume-query", None),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="AAPL")
    args = parser.parse_args()
    symbol = args.symbol.strip().upper()
    if not SAFE_SYMBOL.match(symbol):
        raise SystemExit("symbol must be 1-6 letters")
    session = requests.Session()
    results = []
    for index, (path, params) in enumerate(plan(symbol, datetime.now(timezone.utc).date())):
        if index:
            time.sleep(1.5)
        results.append(probe(session, path, params))
    print(json.dumps({"probe": "occ_layouts", "symbol": symbol,
                      "digits_masked": True, "results": results}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
