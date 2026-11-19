from __future__ import annotations

from datetime import datetime, timezone

from scripts.oss_review import ranked, score

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def _repo(name, **extra):
    row = {"full_name": name, "html_url": f"https://github.com/{name}", "license": "MIT",
           "pushed_at": "2026-11-01T00:00:00Z", "stargazers_count": 1500, "language": "Python",
           "archived": False, "fork": False}
    row.update(extra)
    return row


def test_score_formula_is_fixed_and_documented():
    row = score(_repo("a/b"), now=NOW)
    assert (row["licence_score"], row["maintenance"], row["adoption"], row["stack"]) == (3, 3, 2, 2)
    assert row["total"] == 10
    assert row["core_allowed"] is True


def test_copyleft_unclear_licence_and_archived_projects_score_low():
    assert score(_repo("a/agpl", license="AGPL-3.0"), now=NOW)["core_allowed"] is False
    assert score(_repo("a/none", license="NOASSERTION"), now=NOW)["licence_score"] == 0
    assert score(_repo("a/lgpl", license="LGPL-3.0"), now=NOW)["licence_score"] == 1
    old = score(_repo("a/old", pushed_at="2023-01-01T00:00:00Z"), now=NOW)
    assert old["maintenance"] == 0
    assert score(_repo("a/arch", archived=True), now=NOW)["maintenance"] == 0


def test_standing_decisions_override_the_formula():
    row = score(_repo("kernc/backtesting.py", license="AGPL-3.0"), now=NOW)
    assert "AGPL" in row["standing_decision"]


def test_relevance_screen_excludes_out_of_scope_and_non_compliant_tools():
    from scripts.oss_review import screen
    assert screen(_repo("ccxt/ccxt", description="crypto exchange trading library")) == "crypto venues, outside scope"
    assert "terms block" in screen(_repo("ranaroussi/yfinance", description="Download market data from Yahoo"))
    assert screen(_repo("wasi-master/13ft", description="bypass paywalls")) == "circumvention tool, never used"
    assert screen(_repo("dgunning/edgartools", description="Navigate SEC EDGAR filings")) is None


def test_forks_are_ranked_only_when_named_and_order_is_deterministic():
    snapshot = {"repositories": [
        _repo("x/fork", fork=True),
        _repo("y/named-fork", fork=True, named=True),
        _repo("z/top", stargazers_count=20000),
        _repo("a/tie"), _repo("b/tie"),
    ]}
    names = [row["full_name"] for row in ranked(snapshot, now=NOW)]
    assert "x/fork" not in names
    assert names[0] == "z/top"
    assert names.index("a/tie") < names.index("b/tie")
    assert "y/named-fork" in names


def test_verify_batches_exact_names_resolves_renames_and_reports_missing():
    from scripts import oss_review

    calls = []
    world = {"a/one": _repo("a/one"), "b/two": _repo("b/two"),
             "new-owner/moved": _repo("new-owner/moved", stargazers_count=900)}

    def fake_search(query, per_page):
        calls.append(query)
        if query.startswith("repo:"):
            wanted = {q.split(":", 1)[1].lower() for q in query.split()}
            return [r for n, r in world.items() if n in wanted]
        short = query.split()[0]
        return [r for n, r in world.items() if n.split("/")[1] == short]

    out = oss_review.verify(("a/one", "b/two", "old-owner/moved", "gone/never"), search=fake_search, pause=0, batch=3)
    assert calls[0] == "repo:a/one repo:b/two repo:old-owner/moved" and calls[1] == "repo:gone/never"
    names = {r["full_name"]: r for r in out["repositories"]}
    assert set(names) == {"a/one", "b/two", "new-owner/moved"}
    assert names["new-owner/moved"]["resolved_from"] == "old-owner/moved"
    assert out["not_found"] == ["gone/never"]  # reported, never guessed


def test_integration_registry_uses_snapshot_metadata_and_known_statuses():
    from scripts import build_integration_registry as reg

    seed = {"fetched_at": "2026-11-19T03:00:00+00:00", "repositories": [_repo(n) for n in reg.D]}
    doc = reg.build(seed, {"repositories": [_repo(n) for n in reg.EXTENDED]})
    assert len(doc["candidates"]) == len(reg.D) + len(reg.EXTENDED)
    assert all(c["decision"] in reg.STATUSES for c in doc["candidates"])
    assert all(c["evidence"] in doc["evidence_levels"] for c in doc["candidates"])
    assert all(c["license"] == "MIT" and c["latest_push"] == "2026-11-01" for c in doc["candidates"])
    # copyleft and paid services are never ready for pilot
    by = {c["name"]: c["decision"] for c in doc["candidates"]}
    assert by["backtesting.py"] == by["gammagrid"] == by["python-telegram-bot"] == "REJECTED"
    assert by["sec-api-python"] == "BLOCKED" and by["vectorbt"] == "BLOCKED"
