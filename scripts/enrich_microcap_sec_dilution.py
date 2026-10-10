from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from options_radar.microcap_hunter import assess_microcap_candidate  # noqa: E402
from options_radar.sec_dilution_engine import assess_sec_dilution  # noqa: E402
from options_radar.settings import Settings  # noqa: E402

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
LOCAL_CIK_MAP = Path("data/sec_cik_map.json")


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": settings.sec_user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
    }


def _ticker_map(session: requests.Session, settings: Settings) -> tuple[dict[str, str], str]:
    mapping: dict[str, str] = {}
    local = _load_json(LOCAL_CIK_MAP, {})
    if isinstance(local, dict):
        for symbol, cik in local.items():
            if str(symbol).strip() and str(cik).isdigit():
                mapping[str(symbol).upper()] = str(cik).zfill(10)

    source = "local SEC CIK cache"
    try:
        response = session.get(SEC_TICKERS, headers=_headers(settings), timeout=20)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            for item in payload.values():
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("ticker") or "").upper().strip()
                cik = str(item.get("cik_str") or "")
                if symbol and cik.isdigit():
                    mapping[symbol] = cik.zfill(10)
            source = "SEC company_tickers.json + local cache"
    except requests.RequestException:
        pass
    return mapping, source


def _events_by_symbol(latest_payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    omega = latest_payload.get("omega") if isinstance(latest_payload, dict) else {}
    omega = omega if isinstance(omega, dict) else {}
    intelligence = omega.get("catalyst_intelligence")
    intelligence = intelligence if isinstance(intelligence, dict) else {}
    rows = intelligence.get("by_symbol")
    rows = rows if isinstance(rows, dict) else {}

    output: dict[str, list[dict[str, Any]]] = {}
    for symbol, cluster in rows.items():
        if not isinstance(cluster, dict):
            continue
        members = cluster.get("members")
        output[str(symbol).upper()] = [
            dict(member)
            for member in members
            if isinstance(member, dict)
        ] if isinstance(members, list) else []
    return output


def _candidate_symbols(state: dict[str, Any], maximum: int) -> list[str]:
    symbols = state.get("symbols")
    symbols = symbols if isinstance(symbols, dict) else {}
    ranked: list[tuple[float, float, str]] = []
    for symbol, row in symbols.items():
        if not isinstance(row, dict):
            continue
        market_cap = _number(row.get("market_cap"))
        float_shares = _number(row.get("float_shares"))
        if market_cap > 2_000_000_000:
            continue
        if float_shares > 50_000_000:
            continue
        microcap = row.get("microcap_hunter")
        microcap = microcap if isinstance(microcap, dict) else {}
        score = _number(microcap.get("score"), _number(row.get("send_priority")))
        priority = 1.0 if str(microcap.get("stage") or "") in {"PRIORITY", "WATCH"} else 0.0
        ranked.append((priority, score, str(symbol).upper()))
    ranked.sort(reverse=True)
    return [symbol for _, _, symbol in ranked[:maximum]]


def enrich(
    state: dict[str, Any],
    latest_payload: dict[str, Any],
    *,
    settings: Settings | None = None,
    session: requests.Session | None = None,
    maximum_symbols: int = 12,
    now: datetime | None = None,
) -> dict[str, Any]:
    settings = settings or Settings()
    session = session or requests.Session()
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    mapping, mapping_source = _ticker_map(session, settings)
    events = _events_by_symbol(latest_payload)
    symbols = state.get("symbols")
    symbols = symbols if isinstance(symbols, dict) else {}
    selected = _candidate_symbols(state, maximum_symbols)

    enriched = 0
    unavailable = 0
    errors: dict[str, str] = {}

    for index, symbol in enumerate(selected):
        row = symbols.get(symbol)
        if not isinstance(row, dict):
            continue
        cik = mapping.get(symbol)
        if not cik:
            row["sec_dilution_v2"] = {
                "available": False,
                "reason": "NO_SEC_CIK_MATCH",
                "research_only": True,
                "decision_authority": False,
            }
            unavailable += 1
            continue

        try:
            if index:
                time.sleep(0.12)
            response = session.get(
                SEC_COMPANY_FACTS.format(cik=cik),
                headers=_headers(settings),
                timeout=20,
            )
            response.raise_for_status()
            company_facts = response.json()
            assessment = assess_sec_dilution(
                company_facts if isinstance(company_facts, dict) else {},
                events.get(symbol, []),
                market_cap=_number(row.get("market_cap")),
                float_shares=_number(row.get("float_shares")),
                as_of=reference,
            )
            payload = assessment.as_dict()
            payload["available"] = bool(
                payload.get("share_history", {}).get("available")
                or payload.get("financing", {}).get("event_count", 0)
            )
            payload["cik"] = cik
            payload["observed_at"] = reference.astimezone(timezone.utc).isoformat()
            payload["source"] = "SEC Company Facts + existing SEC catalyst evidence"
            row["sec_dilution_v2"] = payload
            row["microcap_hunter"] = assess_microcap_candidate(
                {"symbol": symbol, **row}
            ).as_dict()
            enriched += 1
        except Exception as exc:
            errors[symbol] = f"{type(exc).__name__}: {exc}"
            row["sec_dilution_v2"] = {
                "available": False,
                "reason": "SEC_COMPANY_FACTS_UNAVAILABLE",
                "error": errors[symbol][:240],
                "cik": cik,
                "research_only": True,
                "decision_authority": False,
            }
            unavailable += 1

    state["sec_dilution_v2"] = {
        "generated_at": reference.astimezone(timezone.utc).isoformat(),
        "research_only": True,
        "decision_authority": False,
        "score_is_probability": False,
        "selected": len(selected),
        "enriched": enriched,
        "unavailable": unavailable,
        "ticker_map_source": mapping_source,
        "errors": errors,
        "policy": (
            "Only top small-cap candidates are queried. Share growth is point-in-time "
            "SEC DEI evidence; financing amounts are announced capacity, not assumed "
            "remaining capacity. Missing SEC data never becomes favorable evidence."
        ),
    }
    return state


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research-only SEC dilution enrichment for Fast Microcap Hunter"
    )
    parser.add_argument("--state", default="data/live/fast_market_state.json")
    parser.add_argument("--latest", default="public/data/latest.json")
    parser.add_argument("--max-symbols", type=int, default=None)
    args = parser.parse_args()

    state_path = Path(args.state)
    latest_path = Path(args.latest)
    if not state_path.exists():
        print("SEC dilution V2: no fast-market state; nothing to enrich")
        return 0

    state = _load_json(state_path, {})
    latest = _load_json(latest_path, {})
    maximum = args.max_symbols or int(os.getenv("MICROCAP_SEC_MAX_SYMBOLS", "12"))
    maximum = max(1, min(25, maximum))

    result = enrich(
        state if isinstance(state, dict) else {},
        latest if isinstance(latest, dict) else {},
        maximum_symbols=maximum,
    )
    _write_json(state_path, result)

    summary = result.get("sec_dilution_v2") or {}
    print(
        "SEC dilution V2: "
        f"selected={summary.get('selected', 0)} "
        f"enriched={summary.get('enriched', 0)} "
        f"unavailable={summary.get('unavailable', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
