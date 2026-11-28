import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fda_under_test", ROOT / "options_radar" / "fda_events.py")
fda = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fda)

ALIASES = {"VRTX": "Vertex Pharmaceuticals Inc", "PFE": "Pfizer Inc", "ABC": "Alpha Labs Inc", "XYZ": "Alpha Labs Corp"}
INDEX = fda.build_name_index(ALIASES)
START, END = date(2026, 9, 21), date(2026, 10, 20)


def test_name_matching_is_conservative():
    assert fda.match_ticker("VERTEX PHARMACEUTICALS INCORPORATED", INDEX) == ("VRTX", "exact_normalised_name")
    assert fda.match_ticker("Pfizer Labs", INDEX) == ("PFE", "exact_normalised_name")
    # Two tickers share a normalised name: no guess.
    assert fda.match_ticker("Alpha Labs", INDEX) == (None, "unmatched")
    assert fda.match_ticker("Teva Pharmaceuticals USA", INDEX) == (None, "unmatched")
    assert fda.match_ticker("", INDEX) == (None, "no_name")


def test_approvals_keep_only_ap_in_window_and_rank_originals():
    rows = [{"application_number": "NDA217123", "sponsor_name": "VERTEX PHARMACEUTICALS INC",
             "products": [{"brand_name": "NEWDRUG"}],
             "submissions": [
                 {"submission_type": "ORIG", "submission_number": "1", "submission_status": "AP",
                  "submission_status_date": "20261015", "review_priority": "PRIORITY",
                  "submission_class_code_description": "Type 1 - New Molecular Entity"},
                 {"submission_type": "SUPPL", "submission_number": "2", "submission_status": "AP",
                  "submission_status_date": "20261001", "submission_class_code_description": "Efficacy"},
                 {"submission_type": "SUPPL", "submission_number": "3", "submission_status": "TA",
                  "submission_status_date": "20261002"},
                 {"submission_type": "SUPPL", "submission_number": "4", "submission_status": "AP",
                  "submission_status_date": "20250101"}]}]
    events = fda.approval_events(rows, INDEX, START, END)
    assert [e["event_type"] for e in events] == ["APPROVAL_ORIGINAL", "APPROVAL_SUPPLEMENT"]
    assert events[0]["ticker"] == "VRTX" and events[0]["importance"] == "HIGH"
    assert events[1]["importance"] == "MEDIUM"
    assert events[0]["official_url"].endswith("ApplNo=217123")
    assert events[0]["date"] == "2026-10-15"


def test_recalls_classified_and_deduplicated():
    row = {"recall_number": "D-0001-2027", "recalling_firm": "Pfizer Inc.", "classification": "Class I",
           "report_date": "20261014", "product_description": "x", "reason_for_recall": "y"}
    events = fda.recall_events([row, dict(row)], INDEX)
    assert len(events) == 1 and events[0]["importance"] == "HIGH" and events[0]["ticker"] == "PFE"


def test_report_policy():
    report = fda.build([], [], generated_at="2026-10-20T20:00:00+00:00", start=START, end=END)
    assert report["schema"] == "ghazi.fda_events.v1"
    assert report["decision_authority"] is False and "CC0" in report["rights"]
    json.dumps(report, allow_nan=False)


def test_script_keeps_previous_file_when_both_endpoints_fail(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("build_fda_under_test", ROOT / "scripts" / "build_fda_events.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    out = tmp_path / "fda.json"
    out.write_text('{"keep": true}')
    monkeypatch.setattr(script, "_get", lambda path, params, attempts=3: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(sys, "argv", ["x", "--output", str(out)])
    assert script.main() == 1 and json.loads(out.read_text()) == {"keep": True}
    monkeypatch.setattr(script, "_get", lambda path, params, attempts=3: [])
    assert script.main() == 0
    assert json.loads(out.read_text())["counts"]["approvals"] == 0


LISTED = {"schema": "ghazi.nasdaq_listed.v1",
          "fields": ["symbol", "issuer", "security", "category", "financial_status", "etf", "equity"],
          "rows": [["COGT", "Cogent Biosciences, Inc.", "Common Stock", "Q", "N", 0, 1],
                   ["BBIO", "BridgeBio Pharma, Inc.", "Common Stock", "Q", "N", 0, 1],
                   ["VRTXX", "Vertex Pharmaceuticals Incorporated", "Common Stock", "Q", "N", 0, 1],
                   ["AAA", "Acme Therapeutics Inc", "Common Stock", "Q", "N", 0, 1],
                   ["AAB", "Acme Pharma Corp", "Common Stock", "Q", "N", 0, 1],
                   ["ETFX", "Cogent Income ETF", "ETF", "G", "N", 1, 0],
                   ["AB", "AB Inc", "Common Stock", "Q", "N", 0, 1]]}


def test_listed_issuers_match_small_sponsors_without_hand_written_aliases():
    """2026-11 audit: COGT and BBIO events stayed unmatched because only 67 curated names were indexed."""
    index = fda.build_name_index(ALIASES, {"BMY": ["Bristol-Myers Squibb Co"]}, fda.listed_issuers(LISTED))
    assert fda.match_ticker("COGENT BIOSCIENCES INC", index) == ("COGT", "listed_issuer_name")
    assert fda.match_ticker("BridgeBio Pharma, Inc.", index) == ("BBIO", "listed_issuer_name")
    assert fda.match_ticker("Bristol-Myers Squibb Company", index) == ("BMY", "reviewed_sponsor_alias")
    # curated names win over the registry; names that normalise to two tickers or too short are not used
    assert fda.match_ticker("Vertex Pharmaceuticals Inc", index) == ("VRTX", "exact_normalised_name")
    assert fda.match_ticker("Acme Inc", index) == (None, "unmatched")
    assert fda.match_ticker("AB Inc", index) == (None, "unmatched")
    assert "ETFX" not in fda.listed_issuers(LISTED)


def test_listed_registry_is_optional():
    assert fda.listed_issuers(None) == {} and fda.listed_issuers({"rows": [["X"]]}) == {}
    assert fda.build_name_index(ALIASES) == fda.build_name_index(ALIASES, None, {})


def test_sec_registry_adds_nyse_issuers_and_drops_ambiguous_share_classes():
    from datetime import datetime, timezone

    from scripts import build_sec_registry as sec

    payload = {"fields": ["cik", "name", "ticker", "exchange"],
               "data": [[14272, "BRISTOL MYERS SQUIBB CO", "BMY", "NYSE"],
                        [1652044, "Alphabet Inc.", "GOOGL", "Nasdaq"], [1652044, "Alphabet Inc.", "GOOG", "Nasdaq"],
                        [99, "Pink Sheet Corp", "PNKS", "OTC"], [5, "Cogent Biosciences, Inc.", "COGT", "Nasdaq"]]}
    built = sec.build(payload, datetime(2026, 11, 28, tzinfo=timezone.utc))
    assert built["fields"] == ["ticker", "cik", "name", "exchange"] and built["counts"]["rows"] == 4
    assert "PNKS" not in {r[0] for r in built["rows"]}
    issuers = fda.registry_issuers(LISTED, built)
    index = fda.build_name_index({}, None, issuers)
    assert fda.match_ticker("Bristol-Myers Squibb Company", index) == ("BMY", "listed_issuer_name")
    assert fda.match_ticker("Alphabet Inc", index) == (None, "unmatched")  # two share classes: no guess
    assert fda.match_ticker("Cogent Biosciences", index)[0] == "COGT"


def test_sec_registry_refuses_without_a_declared_user_agent(tmp_path, monkeypatch, capsys):
    from scripts import build_sec_registry as sec

    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.setattr(sys, "argv", ["x", "--output", str(tmp_path / "out.json")])
    assert sec.main() == 0 and not (tmp_path / "out.json").exists()
    assert "NOT_ATTEMPTED" in capsys.readouterr().out



def test_entity_graph_permanent_cases_cogt_bbio_bmy():
    """Permanent identity cases (owner, PHASE 5): acquisitions and renames by date, from official sources."""
    import json
    from pathlib import Path

    graph = json.loads((Path(__file__).resolve().parents[1] / "data/entity_graph.json").read_text(encoding="utf-8"))
    assert all(e["source"].startswith("https://") and e["effective_from"] for e in graph["entities"])
    assert fda.graph_resolve("Karuna Therapeutics, Inc.", "2026-11-28", graph)[0] == "BMY"
    assert fda.graph_resolve("Karuna Therapeutics", "2024-03-17", graph)[0] == "KRTX"  # before closing
    assert fda.graph_resolve("Celgene", "2026-11-28", graph)[0] == "BMY"
    assert fda.graph_resolve("Eidos Therapeutics", "2026-11-28", graph)[0] == "BBIO"
    assert fda.graph_resolve("Unum Therapeutics Inc", "2026-11-28", graph) == ("COGT", "entity_graph:renamed:since_2020-10-06")
    assert fda.graph_resolve("Karuna Health Partners", "2026-11-28", graph) == (None, "unmatched")  # no fuzzy match
    index = fda.build_name_index({"BMY": "Bristol-Myers Squibb"}, listed={"COGT": "Cogent Biosciences, Inc.",
                                                                          "BBIO": "BridgeBio Pharma, Inc."},
                                 graph=graph, as_of="2026-11-28")
    assert fda.match_ticker("Mirati Therapeutics", index)[0] == "BMY"
    assert fda.match_ticker("Cogent Biosciences", index)[0] == "COGT"
    assert fda.match_ticker("Eidos Therapeutics, Inc.", index) == ("BBIO", "entity_graph:acquired_subsidiary:since_2021-01-26")
    assert fda.match_ticker("Mirati Bio Labs", index) == (None, "unmatched")  # similar text is not a relation
