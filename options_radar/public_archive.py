"""Public-data research archive: vintage rows from bot-state snapshots, Parquet files, DuckDB reports.

Why: the public JSON files on bot-state are snapshots. Each copy replaces the last, so a curve date,
a CFTC week or a first-published claims figure survives only in git history (measured 2026-11-19:
110 Treasury observations in history vs 5 in the latest copy; one DOL week revised after first
publication, which a backtest on the latest copy would see as if it had been known all along).

What is archived: only sources whose terms allow storing and republishing - U.S. government
publications (Treasury, CFTC, DOL, OFR), Wikimedia pageviews (CC0), the NY Fed reference rates
with their required notice - and our own source-health log. Alpaca, Yahoo, Nasdaq.com, Cboe, BLS
and FRED data are never read here.

Vintage model (no look-ahead): a row is written when a key first appears or a reported value
changes. `collected_at` is when our pipeline fetched it, `publisher_time` the publisher's own stamp
when it gives one. `as_of(t)` keeps, per key, the last row collected at or before t. A field the
new copy leaves empty is carried from the previous vintage, so a missing field is not a revision.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "ghazi.public_archive.v1"
NOT_AVAILABLE = "NOT_AVAILABLE_IN_PUBLIC_ARCHIVE"
PREDICTION_OUTCOME_REASON = (
    "Stock and contract outcomes need prices. The public pipeline has no lawful price source "
    "(Yahoo is gated by its terms) and Alpaca data is owner-private: it is never stored in this "
    "public archive. Owner-private evaluation runs on the runner and stores nothing "
    "(scripts/run_opening_fib_history.py).")

Extracted = list[tuple[tuple[Any, ...], tuple[Any, ...], str | None]]  # (key, values, publisher_time)


@dataclass(frozen=True)
class Dataset:
    name: str
    source_path: str
    keys: tuple[tuple[str, str], ...]     # (column, DuckDB type)
    values: tuple[tuple[str, str], ...]
    publisher: str
    rights: str
    attribution: str
    extract: Callable[[dict[str, Any]], Extracted]
    note: str = ""


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None and number == int(number) else None


def _date(value: Any) -> str | None:
    text = str(value or "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _treasury(doc: dict[str, Any]) -> Extracted:
    curve = doc.get("treasury_curve") or {}
    day = _date(curve.get("curve_date"))
    if not curve.get("available") or not day:
        return []
    return [((day, str(tenor)), (_num(value),), None)
            for tenor, value in sorted((curve.get("yields_pct") or {}).items()) if _num(value) is not None]


def _cftc(doc: dict[str, Any]) -> Extracted:
    out: Extracted = []
    for code, market in sorted((doc.get("cftc_index_futures") or {}).items()):
        day = _date((market or {}).get("positions_as_of")) if isinstance(market, dict) else None
        if not day or not market.get("available"):
            continue
        for category, row in sorted((market.get("categories") or {}).items()):
            if isinstance(row, dict):
                out.append(((day, str(code), str(category)),
                            (_int(row.get("net")), _int(row.get("weekly_change")), _num(row.get("cot_index_3y")),
                             _int(market.get("open_interest"))), None))
    return out


def _claims(doc: dict[str, Any]) -> Extracted:
    claims = doc.get("claims") or {}
    if not claims.get("available"):
        return []
    stamp = claims.get("source_last_modified")
    out: Extracted = []
    for row in claims.get("history") or []:
        if isinstance(row, (list, tuple)) and len(row) >= 2 and _date(row[0]) and _int(row[1]) is not None:
            out.append(((_date(row[0]),), (_int(row[1]),), stamp))
    return out


def _nyfed(doc: dict[str, Any]) -> Extracted:
    rates = doc.get("funding_rates") or {}
    if not rates.get("available"):
        return []
    merged: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    for row in rates.get("sofr_history") or []:
        if isinstance(row, (list, tuple)) and len(row) >= 2 and _date(row[0]) and _num(row[1]) is not None:
            merged[("SOFR", _date(row[0]))] = (_num(row[1]), None, None, None)
    for name in ("sofr", "effr"):
        point = rates.get(name) or {}
        if _date(point.get("date")) and _num(point.get("rate")) is not None:
            merged[(name.upper(), _date(point["date"]))] = (
                _num(point.get("rate")), _num(point.get("p1")), _num(point.get("p99")), _num(point.get("volume_bn")))
    return [(key, values, None) for key, values in sorted(merged.items())]


def _ofr(doc: dict[str, Any]) -> Extracted:
    repo = doc.get("repo") or {}
    out: Extracted = []
    for block in repo.values():
        if not isinstance(block, dict) or not block.get("available") or not block.get("mnemonic"):
            continue
        day = _date(block.get("date"))
        if day and _num(block.get("value")) is not None:
            out.append(((str(block["mnemonic"]), day), (_num(block.get("value")), block.get("vintage")),
                        block.get("source_last_update")))
    return sorted(out)


def _wiki(doc: dict[str, Any]) -> Extracted:
    out: Extracted = []
    for row in doc.get("rows") or []:
        if not isinstance(row, dict) or row.get("status") != "OK":
            continue
        day, views = _date(row.get("latest_date")), _int(row.get("latest_views"))
        if row.get("symbol") and day and views is not None:
            out.append(((str(row["symbol"]), day), (views, row.get("title")), None))
    return sorted(out)


HEALTH_ALWAYS = ("gdelt_attention", "fed_monetary")


def _health(doc: dict[str, Any]) -> Extracted:
    """State per source. Before `source_status` existed (2026-11-19) a recovered source simply left
    `source_errors`, so only the sources every copy carries (GDELT, Fed) are tracked for those copies."""
    errors = doc.get("source_errors") if isinstance(doc.get("source_errors"), dict) else {}
    status = doc.get("source_status") if isinstance(doc.get("source_status"), dict) else {}
    tracked = set(HEALTH_ALWAYS) | (set(errors) | set(status) if status else set())
    return [((source,), (str(errors.get(source) or "OK"),), None) for source in sorted(tracked)]


_MACRO = "runtime/public/data/public_macro.json"
_LIQUIDITY = "runtime/public/data/liquidity_monitor.json"
DATASETS: tuple[Dataset, ...] = (
    Dataset("treasury_par_yields", _MACRO, (("curve_date", "DATE"), ("tenor", "VARCHAR")),
            (("yield_pct", "DOUBLE"),), "U.S. Department of the Treasury", "treasury",
            "Source: U.S. Treasury daily par yield curve rates.", _treasury),
    Dataset("cftc_tff_positions", _MACRO,
            (("positions_as_of", "DATE"), ("market_code", "VARCHAR"), ("category", "VARCHAR")),
            (("net", "BIGINT"), ("weekly_change", "BIGINT"), ("cot_index_3y", "DOUBLE"),
             ("open_interest", "BIGINT")),
            "U.S. Commodity Futures Trading Commission", "cftc",
            "Source: CFTC Traders in Financial Futures, futures only.", _cftc),
    Dataset("dol_initial_claims_nsa", _LIQUIDITY, (("week_ending", "DATE"),), (("initial_claims", "BIGINT"),),
            "U.S. Department of Labor, ETA 539", "dol_eta539", "Source: U.S. Department of Labor (ETA 539).",
            _claims, note="Not seasonally adjusted: compare a week only with the same week a year earlier."),
    Dataset("nyfed_reference_rates", _LIQUIDITY, (("rate_type", "VARCHAR"), ("effective_date", "DATE")),
            (("rate_pct", "DOUBLE"), ("p1_pct", "DOUBLE"), ("p99_pct", "DOUBLE"), ("volume_bn", "DOUBLE")),
            "Federal Reserve Bank of New York", "nyfed_reference_rates",
            "Source: Federal Reserve Bank of New York.", _nyfed),
    Dataset("ofr_stfm", _LIQUIDITY, (("mnemonic", "VARCHAR"), ("obs_date", "DATE")),
            (("value", "DOUBLE"), ("vintage", "VARCHAR")), "Office of Financial Research (U.S. Treasury)",
            "ofr_stfm", "Source: Office of Financial Research, Short-term Funding Monitor.", _ofr,
            note="Tri-party rates are informational and not intended to be referenced in contracts."),
    Dataset("wikimedia_pageviews", "runtime/public/data/wiki_attention.json",
            (("symbol", "VARCHAR"), ("view_date", "DATE")), (("views", "BIGINT"), ("article", "VARCHAR")),
            "Wikimedia Foundation (English Wikipedia, human users)", "wikimedia_pageviews",
            "Source: Wikimedia pageviews, CC0 1.0.", _wiki, note="Attention context, not a price signal."),
    Dataset("source_health", "runtime/public/data/free_public_intelligence.json", (("source", "VARCHAR"),),
            (("state", "VARCHAR"),), "GHAZI RADAR (own operational log)", "ghazi_operational",
            "Fetch outcome per public news source; a row marks a change of state.", _health),
)
SOURCE_PATHS = tuple(dict.fromkeys(d.source_path for d in DATASETS))
PROVENANCE = (("collected_at", "TIMESTAMPTZ"), ("stored_at", "TIMESTAMPTZ"), ("publisher_time", "VARCHAR"),
              ("state_commit", "VARCHAR"))


def _parse_time(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else None


def collected_time(doc: dict[str, Any], stored_at: datetime) -> datetime:
    """When the pipeline fetched the copy: its generated_at, never later than the commit."""
    generated = _parse_time(doc.get("generated_at"))
    return generated if generated is not None and generated <= stored_at else stored_at


def vintage_rows(versions: Iterable[tuple[str, datetime, dict[str, Any] | None]],
                 datasets: Iterable[Dataset]) -> dict[str, list[tuple[Any, ...]]]:
    """Versions of one source file (oldest first) -> rows per dataset, one per new or changed value."""
    datasets = tuple(datasets)
    last: dict[str, dict[tuple[Any, ...], tuple[Any, ...]]] = {d.name: {} for d in datasets}
    rows: dict[str, list[tuple[Any, ...]]] = {d.name: [] for d in datasets}
    for commit, stored_at, doc in versions:
        if not isinstance(doc, dict):
            continue
        collected = collected_time(doc, stored_at)
        for dataset in datasets:
            seen = last[dataset.name]
            for key, values, stamp in dataset.extract(doc):
                previous = seen.get(key)
                if previous is not None and all(v is None or p is None or v == p
                                                for v, p in zip(values, previous)):
                    # nothing reported differs: carry missing fields; a newly filled field is a new vintage
                    values = tuple(p if v is None else v for v, p in zip(values, previous))
                    if values == previous:
                        continue
                seen[key] = values
                rows[dataset.name].append((*key, *values, collected, stored_at,
                                           None if stamp is None else str(stamp), commit[:12]))
    return rows


def nyfed_notice(doc: dict[str, Any] | None) -> dict[str, str]:
    notice = ((doc or {}).get("funding_rates") or {}).get("notice")
    return {str(k): str(v) for k, v in notice.items()} if isinstance(notice, dict) else {}


def _columns(dataset: Dataset) -> list[tuple[str, str]]:
    return [*dataset.keys, *dataset.values, *PROVENANCE]


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write_parquet(rows: dict[str, list[tuple[Any, ...]]], out_dir: Path, *,
                  notices: dict[str, str] | None = None,
                  observed_until: dict[str, datetime] | None = None) -> dict[str, int]:
    """One zstd Parquet file per dataset, with publisher, rights and notices in the file metadata,
    and archive_manifest.parquet: per dataset, the collection time of the last copy read (a state
    or value with no later change still held until then)."""
    import duckdb

    out_dir.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    con = duckdb.connect()
    try:
        con.execute("SET TimeZone = 'UTC'")
        con.execute("CREATE TABLE manifest (dataset VARCHAR, observed_until TIMESTAMPTZ, rows BIGINT)")
        con.executemany("INSERT INTO manifest VALUES (?, ?, ?)",
                        [(d.name, (observed_until or {}).get(d.name), len(rows.get(d.name) or []))
                         for d in DATASETS])
        manifest = out_dir / "archive_manifest.parquet"
        con.execute(f"COPY manifest TO {_sql_text(str(manifest))} (FORMAT parquet)")
        for dataset in DATASETS:
            cols = _columns(dataset)
            con.execute(f"CREATE OR REPLACE TABLE t ({', '.join(f'{c} {t}' for c, t in cols)})")
            data = rows.get(dataset.name) or []
            if data:
                con.executemany(f"INSERT INTO t VALUES ({', '.join('?' for _ in cols)})", data)
            meta = {"schema": SCHEMA, "dataset": dataset.name, "publisher": dataset.publisher,
                    "rights": dataset.rights, "attribution": dataset.attribution, "note": dataset.note}
            if dataset.rights == "nyfed_reference_rates":
                meta.update({f"notice_{k}": v for k, v in sorted((notices or {}).items())})
            kv = ", ".join(f"{k}: {_sql_text(v)}" for k, v in meta.items() if v)
            target = out_dir / f"{dataset.name}.parquet"
            order = ", ".join(c for c, _ in dataset.keys) + ", collected_at"
            con.execute(f"COPY (SELECT * FROM t ORDER BY {order}) TO {_sql_text(str(target))} "
                        f"(FORMAT parquet, COMPRESSION zstd, KV_METADATA {{{kv}}})")
            sizes[dataset.name] = target.stat().st_size
    finally:
        con.close()
    return sizes


def _connect(archive: Path) -> Any:
    import duckdb

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    manifest = archive / "archive_manifest.parquet"
    if manifest.exists():
        con.execute(f"CREATE VIEW archive_manifest AS SELECT * FROM read_parquet({_sql_text(str(manifest))})")
    else:
        con.execute("CREATE VIEW archive_manifest AS SELECT NULL::VARCHAR AS dataset, "
                    "NULL::TIMESTAMPTZ AS observed_until, 0::BIGINT AS rows WHERE false")
    for dataset in DATASETS:
        path = archive / f"{dataset.name}.parquet"
        if path.exists():
            con.execute(f"CREATE VIEW {dataset.name}_vintages AS SELECT * FROM read_parquet({_sql_text(str(path))})")
            keys = ", ".join(c for c, _ in dataset.keys)
            con.execute(f"CREATE VIEW {dataset.name} AS SELECT * FROM {dataset.name}_vintages "
                        f"QUALIFY row_number() OVER (PARTITION BY {keys} ORDER BY collected_at DESC) = 1")
    return con


def as_of(archive: Path, dataset: str, when: datetime) -> list[dict[str, Any]]:
    """Per key, the last vintage collected at or before `when` (what the pipeline knew then)."""
    spec = next(d for d in DATASETS if d.name == dataset)
    keys = ", ".join(c for c, _ in spec.keys)
    con = _connect(archive)
    try:
        cur = con.execute(f"SELECT * FROM {dataset}_vintages WHERE collected_at <= ? "
                          f"QUALIFY row_number() OVER (PARTITION BY {keys} ORDER BY collected_at DESC) = 1 "
                          f"ORDER BY {keys}", [when])
        names = [c[0] for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]
    finally:
        con.close()


def _records(con: Any, sql: str) -> list[dict[str, Any]]:
    cur = con.execute(sql)
    names = [c[0] for c in cur.description]
    out = []
    for row in cur.fetchall():
        rec = {}
        for name, value in zip(names, row):
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            elif isinstance(value, float):
                value = round(value, 4)
            rec[name] = value
        out.append(rec)
    return out


def _period_reports(con: Any, unit: str) -> dict[str, Any]:
    p = f"date_trunc('{unit}', {{col}})::DATE"
    treasury = _records(con, f"""
        WITH c AS (
          SELECT curve_date, max(yield_pct) FILTER (WHERE tenor = '2Y') AS y2,
                 max(yield_pct) FILTER (WHERE tenor = '10Y') AS y10,
                 max(yield_pct) FILTER (WHERE tenor = '3M') AS m3
          FROM treasury_par_yields GROUP BY curve_date),
        e AS (SELECT {p.format(col='curve_date')} AS period, max(curve_date) AS last_curve_date,
                     arg_max(y2, curve_date) AS y2, arg_max(y10, curve_date) AS y10, arg_max(m3, curve_date) AS m3,
                     count(*) AS curve_days
              FROM c GROUP BY 1)
        SELECT period, last_curve_date, curve_days, y2 AS yield_2y_pct, y10 AS yield_10y_pct,
               round((y10 - y2) * 100, 1) AS spread_10y_2y_bp, round((y10 - m3) * 100, 1) AS spread_10y_3m_bp,
               round((y10 - lag(y10) OVER (ORDER BY period)) * 100, 1) AS change_10y_bp
        FROM e ORDER BY period""")
    claims = _records(con, f"""
        SELECT {p.format(col='c.week_ending')} AS period, count(*) AS weeks,
               sum(c.initial_claims) AS initial_claims, sum(y.initial_claims) AS same_weeks_year_ago,
               round(100.0 * (sum(c.initial_claims) - sum(y.initial_claims)) / sum(y.initial_claims), 1)
                 AS yoy_pct
        FROM dol_initial_claims_nsa c
        JOIN dol_initial_claims_nsa y ON y.week_ending = c.week_ending - INTERVAL 364 DAY
        GROUP BY 1 ORDER BY 1""")
    rates = _records(con, f"""
        WITH s AS (SELECT effective_date, rate_pct FROM nyfed_reference_rates WHERE rate_type = 'SOFR'),
             e AS (SELECT effective_date, rate_pct FROM nyfed_reference_rates WHERE rate_type = 'EFFR')
        SELECT {p.format(col='s.effective_date')} AS period, count(*) AS sofr_days, avg(s.rate_pct) AS sofr_avg_pct,
               count(e.rate_pct) AS days_with_effr,
               round(avg((s.rate_pct - e.rate_pct) * 100), 1) AS sofr_minus_effr_avg_bp
        FROM s LEFT JOIN e USING (effective_date) GROUP BY 1 ORDER BY 1""")
    cftc = _records(con, f"""
        SELECT {p.format(col='positions_as_of')} AS period, market_code, category,
               max(positions_as_of) AS last_week, arg_max(net, positions_as_of) AS net,
               sum(weekly_change) AS change_in_period, count(*) AS weeks
        FROM cftc_tff_positions GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""")
    ofr = _records(con, f"""
        SELECT {p.format(col='obs_date')} AS period, mnemonic, max(obs_date) AS last_date,
               arg_max(value, obs_date) AS last_value, arg_max(vintage, obs_date) AS vintage
        FROM ofr_stfm GROUP BY 1, 2 ORDER BY 1, 2""")
    # a state lasts until the next change (or the last copy read); hours are split at period boundaries
    health = _records(con, f"""
        WITH v AS (SELECT source, state, collected_at AS s,
                          coalesce(lead(collected_at) OVER (PARTITION BY source ORDER BY collected_at),
                                   (SELECT max(observed_until) FROM archive_manifest
                                    WHERE dataset = 'source_health'),
                                   (SELECT max(collected_at) FROM source_health_vintages)) AS e
                   FROM source_health_vintages),
             p AS (SELECT unnest(generate_series(date_trunc('{unit}', min(s)), date_trunc('{unit}', max(e)),
                                                 INTERVAL 1 {unit})) AS ps FROM v),
             d AS (SELECT p.ps::DATE AS period, v.source, v.state,
                          epoch(least(v.e, p.ps + INTERVAL 1 {unit}) - greatest(v.s, p.ps)) / 3600.0 AS hours
                   FROM v JOIN p ON v.s < p.ps + INTERVAL 1 {unit} AND v.e > p.ps)
        SELECT period, source, round(sum(hours), 1) AS observed_hours,
               round(sum(hours) FILTER (state <> 'OK'), 1) AS failing_hours,
               round(100.0 * coalesce(sum(hours) FILTER (state <> 'OK'), 0) / nullif(sum(hours), 0), 1)
                 AS failing_pct,
               string_agg(DISTINCT state, ',' ORDER BY state) AS states
        FROM d GROUP BY 1, 2 HAVING sum(hours) > 0 ORDER BY 1, 2""")
    return {"treasury": treasury, "dol_claims_nsa": claims, "nyfed_rates": rates, "cftc": cftc,
            "ofr": ofr, "source_health": health}


def coverage(con: Any) -> list[dict[str, Any]]:
    out = []
    for dataset in DATASETS:
        keys = ", ".join(c for c, _ in dataset.keys)
        obs = next((c for c, t in dataset.keys if t == "DATE"), None)
        span = f"min({obs}) AS first_observation, max({obs}) AS last_observation," if obs else ""
        rows = _records(con, f"""
            SELECT '{dataset.name}' AS dataset, count(*) AS rows, count(DISTINCT ({keys})) AS keys,
                   {span} min(collected_at) AS first_collected, max(collected_at) AS last_collected
            FROM {dataset.name}_vintages""")
        primary = dataset.values[0][0]  # a revision = the main reported value changed (not a filled-in field)
        revised = _records(con, f"""
            SELECT count(*) AS revised_keys FROM (SELECT {keys} FROM {dataset.name}_vintages
            GROUP BY {keys} HAVING count(DISTINCT {primary}) > 1)""")
        out.append({**rows[0], **revised[0], "rights": dataset.rights,
                    "publisher": dataset.publisher})
    return out


def report(archive: Path, *, notices: dict[str, str] | None = None,
           history: dict[str, Any] | None = None) -> dict[str, Any]:
    con = _connect(archive)
    try:
        return {
            "schema": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "history": history or {}, "coverage": coverage(con),
            "weekly": _period_reports(con, "week"), "monthly": _period_reports(con, "month"),
            "prediction_outcome": {"status": NOT_AVAILABLE, "reason": PREDICTION_OUTCOME_REASON},
            "notices": {"nyfed_reference_rates": notices or {},
                        "attribution": {d.name: d.attribution for d in DATASETS},
                        "notes": {d.name: d.note for d in DATASETS if d.note}},
            "research_only": True, "decision_authority": False,
        }
    finally:
        con.close()


def markdown_summary(rep: dict[str, Any]) -> str:
    """Short public summary for the job page (coverage, latest month, NY Fed notice)."""
    hist = rep["history"]
    lines = ["## Public data archive (DuckDB / Parquet pilot)", "",
             (f"History: {hist.get('first_commit_at', '?')} → {hist.get('last_commit_at', '?')}"
              f" ({hist.get('versions_read', 0)} file versions)"), "",
             "| dataset | rows | keys | revised keys | observations | rights |", "|---|---|---|---|---|---|"]
    for c in rep["coverage"]:
        span = f"{c.get('first_observation', '—')} → {c.get('last_observation', '—')}"
        lines.append(f"| {c['dataset']} | {c['rows']} | {c['keys']} | {c['revised_keys']} | {span} | {c['rights']} |")
    health = [h for h in rep["monthly"]["source_health"] if h["source"] == "gdelt_attention"]
    if health:
        lines += ["", "GDELT fetch failing share by month: " +
                  ", ".join(f"{h['period'][:7]} {h['failing_pct']}%" for h in health)]
    outcome = rep["prediction_outcome"]
    lines += ["", f"Prediction vs outcome: {outcome['status']} - {outcome['reason']}", ""]
    for text in rep["notices"]["nyfed_reference_rates"].values():
        lines.append(f"> {text}")
    return "\n".join(lines) + "\n"


def dumps(rep: dict[str, Any]) -> str:
    return json.dumps(rep, ensure_ascii=False, indent=1, default=str)
