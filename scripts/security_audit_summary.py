"""Summarise the supply-chain audit (zizmor, pip-audit, pip-licenses) and apply the blocking gate.

Report-only except these, which block (exit 1):
- a High-severity template injection in a workflow (a value expanded into a shell script);
- an external action referenced by tag instead of a commit SHA (unpinned-uses);
- GPL or AGPL code among the runtime dependencies (AGENTS.md: needs explicit licence review).
An unreadable zizmor report also blocks: the gate fails closed when it cannot see.
Everything else (unpinned actions, workflow_run triggers, credential persistence, known
vulnerabilities, weak-copyleft or unknown licences) is listed for review, not blocked.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SEVERITY_ORDER = ("High", "Medium", "Low", "Informational", "Unknown")
# unpinned-uses blocks since 2026-11-19: every external action is pinned to a commit SHA (#452) and
# Dependabot keeps the pins current, so a new tag-only reference is a regression.
BLOCKING_RULES = {("template-injection", "High"), ("unpinned-uses", "High")}
# checked after WEAK_COPYLEFT, so "Lesser General Public License" never lands here
STRONG_COPYLEFT = ("agpl", "affero", "general public license", "gpl-2", "gpl-3", "gplv2", "gplv3", "(gpl)")
WEAK_COPYLEFT = ("lgpl", "lesser general public", "mpl", "mozilla public", "epl", "eclipse public")


def _load(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _path(finding: dict[str, Any]) -> str:
    for loc in finding.get("locations") or []:
        key = ((loc.get("symbolic") or {}).get("key")) or {}
        for value in key.values() if isinstance(key, dict) else []:
            if isinstance(value, dict):
                found = value.get("verbatim_path") or value.get("given_path")
                if found:
                    return str(found)
    return "?"


def zizmor_summary(findings: Any) -> dict[str, Any]:
    if not isinstance(findings, list):
        return {"status": "REPORT_UNREADABLE", "counts": {}, "blocking": []}
    counts: Counter[tuple[str, str]] = Counter()
    blocking = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        rule = str(f.get("ident") or "?")
        severity = str((f.get("determinations") or {}).get("severity") or "Unknown")
        counts[(rule, severity)] += 1
        if (rule, severity) in BLOCKING_RULES:
            blocking.append(f"{rule} in {_path(f)}")
    return {"status": "OK", "total": sum(counts.values()),
            "counts": {f"{r} [{s}]": n for (r, s), n in sorted(
                counts.items(), key=lambda x: (SEVERITY_ORDER.index(x[0][1]) if x[0][1] in SEVERITY_ORDER else 9,
                                               -x[1], x[0][0]))},
            "blocking": sorted(blocking)}


def pip_audit_summary(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
        return {"status": "NOT_RUN", "vulnerable": []}
    vulnerable = []
    for dep in report["dependencies"]:
        vulns = dep.get("vulns") or [] if isinstance(dep, dict) else []
        if vulns:
            ids = ", ".join(sorted(str(v.get("id")) for v in vulns if isinstance(v, dict)))
            vulnerable.append(f"{dep.get('name')} {dep.get('version')}: {ids}")
    return {"status": "OK", "dependencies": len(report["dependencies"]), "vulnerable": vulnerable}


def licence_class(text: str) -> str:
    low = (text or "").lower()
    if not low.strip() or "unknown" in low:
        return "UNKNOWN"
    if any(k in low for k in WEAK_COPYLEFT):
        return "WEAK_COPYLEFT"
    if any(k in low for k in STRONG_COPYLEFT) or low.strip() in ("gpl", "agpl"):
        return "STRONG_COPYLEFT"
    return "PERMISSIVE"


def licence_summary(rows: Any) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {"status": "NOT_RUN", "classes": {}, "review": [], "blocking": []}
    classes: Counter[str] = Counter()
    review, blocking = [], []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cls = licence_class(str(row.get("License") or ""))
        classes[cls] += 1
        line = f"{row.get('Name')} {row.get('Version')}: {str(row.get('License') or 'UNKNOWN')[:80]}"
        if cls == "STRONG_COPYLEFT":
            blocking.append(line)
        elif cls != "PERMISSIVE":
            review.append(f"{cls}: {line}")
    return {"status": "OK", "classes": dict(classes), "review": sorted(review), "blocking": sorted(blocking)}


def markdown(z: dict[str, Any], a: dict[str, Any], lic: dict[str, Any]) -> str:
    out = ["## Security audit (report-only except the blocking rules)", "",
           f"**Workflows (zizmor):** {z['status']}" + (f", {z.get('total', 0)} findings" if z["status"] == "OK" else "")]
    out += [f"- {k}: {n}" for k, n in z.get("counts", {}).items()]
    out += ["", f"**Runtime dependencies (pip-audit):** {a['status']}" +
            (f", {a.get('dependencies', 0)} checked, {len(a['vulnerable'])} with known vulnerabilities" if a["status"] == "OK" else "")]
    out += [f"- {v}" for v in a.get("vulnerable", [])]
    out += ["", f"**Runtime dependency licences:** {lic['status']} {lic.get('classes', {})}"]
    out += [f"- {v}" for v in lic.get("review", [])]
    blocking = gate(z, lic)
    out += ["", "**Blocking:** " + ("none" if not blocking else "")]
    out += [f"- {b}" for b in blocking]
    return "\n".join(out) + "\n"


def gate(z: dict[str, Any], lic: dict[str, Any]) -> list[str]:
    reasons = []
    if z["status"] != "OK":
        reasons.append("zizmor report unreadable (gate fails closed)")
    reasons += [f"High-severity {b}" for b in z.get("blocking", [])]
    reasons += [f"GPL/AGPL runtime dependency: {b}" for b in lic.get("blocking", [])]
    return reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zizmor", type=Path, required=True)
    parser.add_argument("--pip-audit", type=Path)
    parser.add_argument("--licenses", type=Path)
    args = parser.parse_args(argv)
    z = zizmor_summary(_load(args.zizmor))
    a = pip_audit_summary(_load(args.pip_audit))
    lic = licence_summary(_load(args.licenses))
    sys.stdout.write(markdown(z, a, lic))
    blocking = gate(z, lic)
    for reason in blocking:
        print(f"::error title=Security audit::{reason}", file=sys.stderr)
    for v in a.get("vulnerable", []):
        print(f"::warning title=Known vulnerability::{v}", file=sys.stderr)
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
