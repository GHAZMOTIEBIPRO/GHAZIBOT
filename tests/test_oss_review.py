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
