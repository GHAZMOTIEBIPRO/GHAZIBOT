"""Public-data archive: vintages without look-ahead, permitted sources only, Parquet + DuckDB reports."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from options_radar import output_policy
from options_radar import public_archive as pa

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
NOTICE = {"SOFR": "The SOFR is subject to the Terms of Use posted at newyorkfed.org."}


def _liquidity(generated: datetime, claims: list[list], sofr_point=None, notice=True) -> dict:
    point = sofr_point or {"date": "2026-10-30", "rate": 3.9, "p1": 3.85, "p99": 3.99, "volume_bn": 3000}
    return {"generated_at": generated.isoformat(),
            "claims": {"available": True, "source_last_modified": "Wed, 28 Oct 2026 20:51:00 GMT",
                       "history": claims},
            "funding_rates": {"available": True, "sofr": point, "notice": NOTICE if notice else None,
                              "sofr_history": [["2026-10-29", 3.88], ["2026-10-30", 3.9]]},
            "repo": {"tri_party_rate": {"available": True, "mnemonic": "REPO-TRI_AR_OO-P", "date": "2026-10-30",
                                        "value": 3.91, "vintage": "Preliminary",
                                        "source_last_update": "2026-10-31 15:08:29"}}}


def _liq_sets():
    return [d for d in pa.DATASETS if d.source_path.endswith("liquidity_monitor.json")]


def test_vintages_keep_first_publication_and_add_a_row_only_for_a_change():
    week_ago = [["2025-10-25", 230000], ["2026-10-24", 178986]]
    revised = [["2025-10-25", 230000], ["2026-10-24", 179009]]
    rows = pa.vintage_rows([("a" * 40, T0, _liquidity(T0 - timedelta(minutes=5), week_ago)),
                            ("b" * 40, T0 + timedelta(days=1), _liquidity(T0 + timedelta(hours=23), week_ago)),
                            ("c" * 40, T0 + timedelta(days=2), _liquidity(T0 + timedelta(days=2), revised))],
                           _liq_sets())
    claims = rows["dol_initial_claims_nsa"]
    assert [(r[0], r[1]) for r in claims] == [("2025-10-25", 230000), ("2026-10-24", 178986), ("2026-10-24", 179009)]
    first = claims[1]
    assert first[2] == T0 - timedelta(minutes=5)          # collected_at: when we fetched it
    assert first[4] == "Wed, 28 Oct 2026 20:51:00 GMT"    # the publisher's own time stamp
    assert first[5] == "a" * 12
    # an unchanged later copy adds nothing; the OFR row and both SOFR keys appear once
    assert len(rows["ofr_stfm"]) == 1 and len(rows["nyfed_reference_rates"]) == 2


def test_a_missing_field_is_not_a_revision_but_a_changed_value_is():
    full = _liquidity(T0, [])
    sparse = _liquidity(T0 + timedelta(hours=1), [], sofr_point={"date": "2026-10-29", "rate": 3.88})
    moved = _liquidity(T0 + timedelta(hours=2), [], sofr_point={"date": "2026-10-30", "rate": 3.95})
    rows = pa.vintage_rows([("a" * 40, T0, full), ("b" * 40, T0 + timedelta(hours=1), sparse),
                            ("c" * 40, T0 + timedelta(hours=2), moved)], _liq_sets())["nyfed_reference_rates"]
    oct30 = [r for r in rows if r[1] == "2026-10-30"]
    # 10-30 first full (with percentiles); copy b only has it in history (rate, no percentiles): no row;
    # copy c reports another rate for 10-30: a new vintage, percentiles not invented
    assert [(r[2], r[3]) for r in oct30] == [(3.9, 3.85), (3.95, None)]


def test_collected_at_is_never_later_than_the_commit():
    late = {"generated_at": (T0 + timedelta(hours=3)).isoformat()}
    assert pa.collected_time(late, T0) == T0
    assert pa.collected_time({"generated_at": "not a time"}, T0) == T0
    assert pa.collected_time({"generated_at": (T0 - timedelta(minutes=1)).isoformat()}, T0) < T0


def test_health_tracks_gdelt_and_fed_always_and_other_sources_only_with_a_full_status():
    old = {"generated_at": T0.isoformat(), "source_errors": {"gdelt_attention": "HTTP_429",
                                                            "press_wire_prnewswire": "ReadTimeout"}}
    assert {k[0]: v[0] for k, v, _ in pa.DATASETS[-1].extract(old)} == {"gdelt_attention": "HTTP_429",
                                                                         "fed_monetary": "OK"}
    new = {**old, "source_status": {"gdelt_attention": {}, "fed_monetary": {}, "press_wire_prnewswire": {}}}
    assert {k[0] for k, _, _ in pa.DATASETS[-1].extract(new)} == {"gdelt_attention", "fed_monetary",
                                                                  "press_wire_prnewswire"}


def test_only_sources_with_verified_storage_and_public_display_rights_are_archived():
    rights = json.loads((ROOT / "data/source_rights.json").read_text(encoding="utf-8"))
    rights = rights.get("providers", rights)
    for dataset in pa.DATASETS:
        if dataset.rights == "ghazi_operational":
            continue
        if output_policy.decide(dataset.rights, "publish_raw", {}).allowed:
            continue
        entry = rights[dataset.rights]["rights"]
        assert entry["persistent_storage"]["status"] == "VERIFIED", dataset.name
        assert entry["public_display_raw"]["status"] == "VERIFIED", dataset.name
    text = " ".join(pa.SOURCE_PATHS).lower()
    for forbidden in ("alpaca", "private", "yahoo", "nasdaq", "cboe", "fred", "bls", "signal_tracking"):
        assert forbidden not in text
    assert set(pa.SOURCE_PATHS) == {f"runtime/public/data/{n}.json" for n in
                                    ("public_macro", "liquidity_monitor", "wiki_attention", "free_public_intelligence")}


def _versions():
    claims_v1 = [["2025-10-25", 230000], ["2025-11-01", 220000], ["2026-10-24", 178986], ["2026-10-31", 200000]]
    claims_v2 = [["2025-10-25", 230000], ["2025-11-01", 220000], ["2026-10-24", 179009], ["2026-10-31", 200000]]
    return [("a" * 40, T0, _liquidity(T0, claims_v1)),
            ("b" * 40, T0 + timedelta(days=3), _liquidity(T0 + timedelta(days=3), claims_v2))]


def test_parquet_files_as_of_queries_and_reports(tmp_path):
    pytest.importorskip("duckdb")
    rows = pa.vintage_rows(_versions(), _liq_sets())
    health = [("h" * 40, T0 + timedelta(days=d), {"generated_at": (T0 + timedelta(days=d)).isoformat(),
                                                   "source_errors": {"gdelt_attention": "HTTP_429"} if d < 7 else {}})
              for d in (0, 7, 8)]
    rows.update(pa.vintage_rows(health, [pa.DATASETS[-1]]))
    sizes = pa.write_parquet(rows, tmp_path, notices=NOTICE,
                             observed_until={"source_health": T0 + timedelta(days=8)})
    assert set(sizes) == {d.name for d in pa.DATASETS} and all(v > 0 for v in sizes.values())

    # no look-ahead: before the revision the first published figure is what was known
    before = pa.as_of(tmp_path, "dol_initial_claims_nsa", T0 + timedelta(days=1))
    after = pa.as_of(tmp_path, "dol_initial_claims_nsa", T0 + timedelta(days=4))
    pick = {str(r["week_ending"]): r["initial_claims"] for r in before}
    assert pick["2026-10-24"] == 178986
    assert {str(r["week_ending"]): r["initial_claims"] for r in after}["2026-10-24"] == 179009
    assert pa.as_of(tmp_path, "dol_initial_claims_nsa", T0 - timedelta(days=1)) == []

    import duckdb
    meta = duckdb.sql(f"SELECT key::VARCHAR k, value::VARCHAR v FROM parquet_kv_metadata('{tmp_path}/"
                      "nyfed_reference_rates.parquet')").fetchall()
    assert ("notice_SOFR", NOTICE["SOFR"]) in meta and ("rights", "nyfed_reference_rates") in meta

    rep = pa.report(tmp_path, notices=NOTICE)
    cov = {c["dataset"]: c for c in rep["coverage"]}
    assert cov["dol_initial_claims_nsa"]["revised_keys"] == 1 and cov["dol_initial_claims_nsa"]["keys"] == 4
    oct_claims = next(r for r in rep["monthly"]["dol_claims_nsa"] if r["period"] == "2026-10-01")
    # NSA: each week only against the same week a year earlier (364 days), latest vintage
    assert (oct_claims["initial_claims"], oct_claims["same_weeks_year_ago"]) == (379009, 450000)
    gdelt = [h for h in rep["weekly"]["source_health"] if h["source"] == "gdelt_attention"]
    # failing for exactly 7 days from Monday noon: split across the two calendar weeks it spans
    assert sum(h["failing_hours"] or 0 for h in gdelt) == pytest.approx(168.0)
    assert len(gdelt) == 2 and gdelt[-1]["observed_hours"] == pytest.approx(36.0)
    assert rep["prediction_outcome"]["status"] == pa.NOT_AVAILABLE
    assert rep["notices"]["nyfed_reference_rates"] == NOTICE and rep["decision_authority"] is False
    summary = pa.markdown_summary({**rep, "history": {"versions_read": 2}})
    assert NOTICE["SOFR"] in summary and "NOT_AVAILABLE_IN_PUBLIC_ARCHIVE" in summary


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_builder_reads_every_committed_version_from_git(tmp_path):
    pytest.importorskip("duckdb")
    from scripts import build_public_archive as build

    repo = tmp_path / "state"
    target = repo / "runtime/public/data/liquidity_monitor.json"
    target.parent.mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "bot-state", str(repo))
    for sha_seed, (_, _, doc) in zip("ab", _versions()):
        target.write_text(json.dumps(doc), encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", sha_seed)
    rows, history, notices = build.collect(repo, "bot-state")
    assert history["versions_read"] == 2 and history["files"]["runtime/public/data/liquidity_monitor.json"][
        "unreadable"] == 0
    assert len(rows["dol_initial_claims_nsa"]) == 5 and notices == NOTICE
    out = tmp_path / "archive"
    assert build.main(["--repo", str(repo), "--ref", "bot-state", "--out", str(out)]) == 0
    rep = json.loads((out / "archive_report.json").read_text(encoding="utf-8"))
    assert rep["measurements"]["rows"]["dol_initial_claims_nsa"] == 5 and (out / "SUMMARY.md").exists()


def test_read_blobs_reports_missing_objects():
    from scripts import build_public_archive as build

    assert build.read_blobs(ROOT, ["0" * 40 + ":nothing.json"]) == [None]


def test_archive_workflow_is_read_only_secret_free_and_uploads_only_public_files():
    text = (ROOT / ".github/workflows/public-archive.yml").read_text(encoding="utf-8")
    spec = yaml.safe_load(text)
    assert spec["permissions"] == {"contents": "read"}
    assert "secrets." not in text and "git push" not in text
    steps = spec["jobs"]["build"]["steps"]
    checkout = next(s for s in steps if "actions/checkout@" in str(s.get("uses")))
    assert checkout["with"]["persist-credentials"] is False
    upload = next(s for s in steps if "upload-artifact@" in str(s.get("uses")))
    assert str(upload["with"]["path"]).startswith("${{ runner.temp }}/public-archive")
    assert all("@" in str(s["uses"]) and len(str(s["uses"]).split("@")[1].split()[0]) == 40
               for s in steps if s.get("uses"))
    assert (ROOT / "requirements-archive.txt").read_text(encoding="utf-8").strip().startswith("duckdb==")
    # run 44504097132 failed with only duckdb installed: the options_radar package imports pandas
    install = next(s["run"] for s in steps if "pip install" in str(s.get("run")))
    assert "app/requirements.txt" in install and "app/requirements-archive.txt" in install
