"""Supply-chain audit summary: which findings block, and that the gate fails closed."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from scripts import security_audit_summary as sa

ROOT = Path(__file__).resolve().parents[1]


def finding(rule: str, severity: str, path: str = ".github/workflows/x.yml") -> dict:
    return {"ident": rule, "determinations": {"severity": severity, "confidence": "High"},
            "locations": [{"symbolic": {"key": {"Local": {"verbatim_path": path}}}}]}


def test_only_high_template_injection_unpinned_actions_and_gpl_runtime_deps_block():
    z = sa.zizmor_summary([finding("unpinned-uses", "High", ".github/workflows/new.yml"),
                           finding("dangerous-triggers", "High"), finding("artipacked", "Medium"),
                           finding("template-injection", "Informational"),
                           finding("template-injection", "High", ".github/workflows/stock-radar.yml")])
    assert z["blocking"] == ["template-injection in .github/workflows/stock-radar.yml",
                             "unpinned-uses in .github/workflows/new.yml"]
    lic = sa.licence_summary([{"Name": "a", "Version": "1", "License": "MIT License"},
                              {"Name": "certifi", "Version": "2", "License": "Mozilla Public License 2.0 (MPL 2.0)"},
                              {"Name": "peewee", "Version": "3", "License": "UNKNOWN"},
                              {"Name": "evil", "Version": "4", "License": "GNU Affero General Public License v3"}])
    assert lic["classes"] == {"PERMISSIVE": 1, "WEAK_COPYLEFT": 1, "UNKNOWN": 1, "STRONG_COPYLEFT": 1}
    assert lic["blocking"] == ["evil 4: GNU Affero General Public License v3"]
    reasons = sa.gate(z, lic)
    assert len(reasons) == 3 and reasons[0].startswith("High-severity template-injection")


def test_lgpl_is_review_not_block_and_unreadable_report_fails_closed(tmp_path):
    lic = sa.licence_summary([{"Name": "l", "Version": "1", "License": "GNU Lesser General Public License v3 (LGPLv3)"}])
    assert lic["blocking"] == [] and lic["review"][0].startswith("WEAK_COPYLEFT")
    assert sa.licence_class("GNU General Public License v3 (GPLv3)") == "STRONG_COPYLEFT"
    assert sa.licence_class("BSD License") == sa.licence_class("Apache Software License") == "PERMISSIVE"
    bad = tmp_path / "z.json"
    bad.write_text("not json", encoding="utf-8")
    assert sa.main(["--zizmor", str(bad)]) == 1  # cannot see -> blocks
    good = tmp_path / "ok.json"
    good.write_text(json.dumps([finding("dangerous-triggers", "High")]), encoding="utf-8")
    audit = tmp_path / "a.json"
    audit.write_text(json.dumps({"dependencies": [{"name": "x", "version": "1", "vulns": [{"id": "PYSEC-1"}]}]}))
    assert sa.main(["--zizmor", str(good), "--pip-audit", str(audit)]) == 0  # vulnerabilities are reported
    assert sa.pip_audit_summary(json.loads(audit.read_text()))["vulnerable"] == ["x 1: PYSEC-1"]


def test_workflow_is_read_only_pinned_and_not_a_privileged_trigger():
    text = (ROOT / ".github/workflows/security-audit.yml").read_text(encoding="utf-8")
    spec = yaml.safe_load(text)
    assert spec["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in spec[True] and "workflow_run" not in spec[True]
    assert "${{ secrets." not in text
    for tool in ("zizmor==", "pip-audit==", "pip-licenses=="):
        assert tool in text
    steps = spec["jobs"]["audit"]["steps"]
    assert steps[0]["with"]["persist-credentials"] is False
    gate = next(s for s in steps if s.get("name") == "Summary and gate")
    assert gate["shell"] == "bash" and "security_audit_summary.py" in gate["run"]


def test_every_external_action_is_pinned_to_a_commit_and_dependabot_keeps_it_current():
    pattern = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
    files = sorted((ROOT / ".github").glob("workflows/*.yml")) + sorted((ROOT / ".github").glob("actions/*/action.yml"))
    refs = [(p.name, ref) for p in files for ref in pattern.findall(p.read_text(encoding="utf-8"))]
    external = [(n, r) for n, r in refs if not r.startswith("./")]
    assert external and all(re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", r) for _, r in external), \
        [x for x in external if not re.search(r"@[0-9a-f]{40}$", x[1])][:5]
    dependabot = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    assert any(u["package-ecosystem"] == "github-actions" for u in dependabot["updates"])


def test_flagged_workflow_inputs_reach_the_shell_as_data_not_code():
    # zizmor template-injection [High] on 2026-11-19: both now pass the value through env
    radar = (ROOT / ".github/workflows/stock-radar.yml").read_text(encoding="utf-8")
    assert 'current="${{ inputs.source_run_id }}"' not in radar
    assert "SOURCE_RUN_ID: ${{ inputs.source_run_id }}" in radar
    options = (ROOT / ".github/workflows/options-radar.yml").read_text(encoding="utf-8")
    assert '"${{ github.event.schedule }}"' not in options and "EVENT_SCHEDULE:" in options
