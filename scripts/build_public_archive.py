"""Build the public-data research archive (Parquet) and its weekly/monthly report from bot-state history.

Reads every committed version of the public source files with `git log` + one `git cat-file --batch`
process, turns them into vintage rows (options_radar.public_archive), writes one zstd Parquet file per
dataset and a JSON report computed with DuckDB. bot-state history is the durable store: the archive is
derived from it and can be rebuilt at any time. Nothing is pushed anywhere.

  python -m scripts.build_public_archive --repo . --ref origin/bot-state --out archive
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from options_radar import public_archive as pa


def list_versions(repo: Path, ref: str, path: str) -> list[tuple[str, datetime]]:
    """Commits that changed `path` on `ref`, oldest first, with their commit times."""
    out = subprocess.run(["git", "-C", str(repo), "log", "--reverse", "--format=%H %cI", ref, "--", path],
                         capture_output=True, text=True, check=True).stdout
    versions = []
    for line in out.splitlines():
        sha, _, when = line.partition(" ")
        if sha and when:
            versions.append((sha, datetime.fromisoformat(when)))
    return versions


def read_blobs(repo: Path, specs: list[str]) -> list[bytes | None]:
    """`<sha>:<path>` -> content, through one `git cat-file --batch` process (None when missing)."""
    if not specs:
        return []
    raw = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], input="\n".join(specs).encode() + b"\n",
                         capture_output=True, check=True).stdout
    out: list[bytes | None] = []
    pos = 0
    for _ in specs:
        end = raw.index(b"\n", pos)
        header = raw[pos:end].split()
        pos = end + 1
        if len(header) < 3 or header[1] == b"missing":
            out.append(None)
            continue
        size = int(header[2])
        out.append(raw[pos:pos + size])
        pos += size + 1
    return out


def _json(blob: bytes | None) -> dict[str, Any] | None:
    if blob is None:
        return None
    try:
        doc = json.loads(blob)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def collect(repo: Path, ref: str) -> tuple[dict[str, list[tuple[Any, ...]]], dict[str, Any], dict[str, str]]:
    """Rows per dataset, a history record (incl. `observed_until` per dataset) and the NY Fed notice."""
    rows: dict[str, list[tuple[Any, ...]]] = {}
    history: dict[str, Any] = {"ref": ref, "versions_read": 0, "bytes_read": 0, "files": {},
                               "observed_until": {}}
    notices: dict[str, str] = {}
    shallow = subprocess.run(["git", "-C", str(repo), "rev-parse", "--is-shallow-repository"],
                             capture_output=True, text=True, check=False).stdout.strip()
    history["shallow_clone"] = shallow == "true"
    firsts, lasts = [], []
    for path in pa.SOURCE_PATHS:
        versions = list_versions(repo, ref, path)
        blobs = read_blobs(repo, [f"{sha}:{path}" for sha, _ in versions])
        docs = [_json(b) for b in blobs]
        history["versions_read"] += len(versions)
        history["bytes_read"] += sum(len(b) for b in blobs if b)
        history["files"][path] = {"versions": len(versions), "unreadable": sum(d is None for d in docs),
                                  "first": versions[0][1].isoformat() if versions else None,
                                  "last": versions[-1][1].isoformat() if versions else None}
        if versions:
            firsts.append(versions[0][1])
            lasts.append(versions[-1][1])
        datasets = [d for d in pa.DATASETS if d.source_path == path]
        rows.update(pa.vintage_rows(((sha, when, doc) for (sha, when), doc in zip(versions, docs)), datasets))
        readable = [(when, doc) for (_, when), doc in zip(versions, docs) if doc is not None]
        if readable:
            until = pa.collected_time(readable[-1][1], readable[-1][0])
            history["observed_until"].update({d.name: until for d in datasets})
        for doc in reversed(docs):
            if pa.nyfed_notice(doc):
                notices = notices or pa.nyfed_notice(doc)
                break
    history["first_commit_at"] = min(firsts).isoformat() if firsts else None
    history["last_commit_at"] = max(lasts).isoformat() if lasts else None
    return rows, history, notices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--ref", default="origin/bot-state")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    t0 = time.perf_counter()
    rows, history, notices = collect(args.repo, args.ref)
    t1 = time.perf_counter()
    sizes = pa.write_parquet(rows, args.out, notices=notices, observed_until=history["observed_until"])
    history["observed_until"] = {k: v.isoformat() for k, v in history["observed_until"].items()}
    t2 = time.perf_counter()
    rep = pa.report(args.out, notices=notices, history=history)
    t3 = time.perf_counter()
    rep["measurements"] = {"read_and_normalise_s": round(t1 - t0, 2), "write_parquet_s": round(t2 - t1, 2),
                           "report_queries_s": round(t3 - t2, 2), "json_bytes_read": history["bytes_read"],
                           "parquet_bytes": sum(sizes.values()), "parquet_bytes_by_dataset": sizes,
                           "rows": {k: len(v) for k, v in rows.items()}}
    (args.out / "archive_report.json").write_text(pa.dumps(rep) + "\n", encoding="utf-8")
    (args.out / "SUMMARY.md").write_text(pa.markdown_summary(rep), encoding="utf-8")
    m = rep["measurements"]
    print(f"Public archive: {history['versions_read']} versions, {sum(m['rows'].values())} rows, "
          f"{m['json_bytes_read']} JSON bytes -> {m['parquet_bytes']} Parquet bytes; "
          f"read {m['read_and_normalise_s']} s, write {m['write_parquet_s']} s, report {m['report_queries_s']} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
