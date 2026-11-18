"""Build runtime/public/data/wiki_attention.json (Wikipedia pageviews attention for U.S. leaders).

Standard library only; modules are loaded by file path (the package __init__ imports pandas).
A refused (401/403/451) or failed article is recorded under "errors" and never retried or worked
around. If every article fails, the previous file is kept and marked `kept_previous_copy`.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


hf = _load("ghazi_http_fetch", "options_radar/http_fetch.py")
wa = _load("ghazi_wiki_attention", "options_radar/wiki_attention.py")


def collect(*, now: datetime, fetch=hf.fetch) -> dict[str, Any]:
    start, end = wa.window(now.date())
    rows, errors = [], {}
    for symbol, (title, _) in wa.LEADERS.items():
        result = fetch(wa.url_for(title, start, end), attempts=2, timeout=20, min_interval=1.0)
        if not result.ok:
            errors[symbol] = result.status()
            continue
        try:
            series = wa.parse_items(json.loads(result.body.decode("utf-8")))
        except (UnicodeDecodeError, ValueError):
            errors[symbol] = "INVALID_JSON"
            continue
        rows.append(wa.summarize(symbol, series))
    return wa.build(rows, errors=errors, now=now)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    doc = collect(now=now)
    ok = sum(1 for r in doc["rows"] if r.get("status") == "OK")
    if ok == 0 and args.output.exists():
        try:
            previous = json.loads(args.output.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
        if isinstance(previous, dict) and previous.get("schema") == wa.SCHEMA:
            previous.update(kept_previous_copy=True, last_attempt_at=now.isoformat(), last_errors=doc["errors"])
            doc = previous
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Wiki attention: {ok}/{len(wa.LEADERS)} articles OK, data through {doc.get('data_through')}, "
          f"errors {doc.get('errors') or doc.get('last_errors')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
