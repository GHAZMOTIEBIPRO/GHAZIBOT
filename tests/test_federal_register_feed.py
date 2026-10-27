from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from scripts import build_federal_register_feed as fr

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cw_fr_test", ROOT / "scripts" / "build_catalyst_watchlist.py")
cw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cw)
NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def doc(title, agency, dtype="Notice", n="2026-1", day="2026-10-27"):
    return {"title": title, "agency": agency, "type": dtype, "document_number": n, "publication_date": day,
            "html_url": f"https://www.federalregister.gov/documents/2026/10/27/{n}/x"}


FAA = "federal-aviation-administration"
FTC = "federal-trade-commission"
FDA = "food-and-drug-administration"
FERC = "federal-energy-regulatory-commission"
DOCS = [
    doc("Airworthiness Directives; The Boeing Company Airplanes", FAA, "Rule", "a1"),
    doc("Airworthiness Directives; CFM International, S.A. Engines", FAA, "Proposed Rule", "a2"),
    doc("Airworthiness Directives; Ontic Engineering and Manufacturing, Inc. (Type Certificate Previously Held by "
        "Swearingen) Airplanes", FAA, "Rule", "a3"),
    doc("Special Conditions: Embraer S.A. Model ERJ 190-400 Airplane; Embraer Enhanced Takeoff System", FAA,
        "Proposed Rule", "a4"),
    doc("Publicis and LiveRamp; Analysis of Proposed Agreement Containing Consent Order To Aid Public Comment", FTC,
        n="t1"),
    doc("FleetCor Technologies; Analysis of Proposed Consent Order To Aid Public Comment", FTC, n="t2"),
    doc("Amneal Pharmaceuticals of New York, LLC; Withdrawal of Approval of Abbreviated New Drug Application for "
        "Celecoxib Capsules", FDA, n="f1"),
    doc("Teva Pharmaceuticals USA, Inc., et al.; Withdrawal of Approval of 15 Abbreviated New Drug Applications; "
        "Correction", FDA, n="f2"),
    doc("Issuance of Priority Review Voucher; Rare Pediatric Disease Product; ZANVASTRO (Zilganersen)", FDA, n="f3"),
    doc("Virginia Electric and Power Company d/b/a Dominion Energy Virginia, Allegheny Generating Company, and Bath "
        "County Energy, LLC; Notice of Revised Schedule for Environmental Assessment", FERC, n="e1"),
    doc("Agency Information Collection Activities; Proposed Collection; Comment Request", FDA, n="noise"),
    doc("Combined Notice of Filings #1", FERC, n="noise2"),
    doc("U.S.-Origin Statements on Seafood; Draft Guidance for Industry; Availability", FDA, n="g1"),
]
BODIES = {"f3": "The Food and Drug Administration (FDA) has issued a priority review voucher to Ionis "
                "Pharmaceuticals, Inc. for ZANVASTRO (zilganersen)."}


def report():
    return fr.build(DOCS, {"FDA": 5}, NOW, BODIES)


def test_each_document_type_reads_the_company_with_its_own_pattern():
    r = {x["document_number"]: x for x in report()["linked"] + report()["company_unlinked"]}
    assert r["a1"]["kind"] == "FR_AIRWORTHINESS_DIRECTIVE" and r["a1"]["companies"] == ["The Boeing Company"]
    assert r["a2"]["kind"] == "FR_PROPOSED_AIRWORTHINESS_DIRECTIVE"
    assert r["a3"]["companies"] == ["Ontic Engineering and Manufacturing, Inc."]
    assert r["a4"]["kind"] == "FR_SPECIAL_CONDITIONS" and r["a4"]["companies"] == ["Embraer S.A."]
    assert r["t1"]["companies"] == ["Publicis", "LiveRamp"]
    assert r["f2"]["companies"] == ["Teva Pharmaceuticals USA, Inc."]
    assert r["f3"]["companies"] == ["Ionis Pharmaceuticals, Inc."]          # sponsor from the body only
    assert "Virginia Electric and Power Company" in r["e1"]["companies"]


def test_links_are_exact_reviewed_names_with_relation_and_exclusions_are_explained():
    r = {x["document_number"]: x for x in report()["linked"] + report()["company_unlinked"]}
    tick = lambda n: sorted(x["ticker"] for x in r[n]["links"])
    assert tick("a1") == ["BA"] and tick("a4") == ["ERJ"] and tick("t1") == ["RAMP"]
    assert r["t2"]["links"][0]["ticker"] == "CPAY" and r["t2"]["links"][0]["relation"] == "RENAMED_SAME_ENTITY"
    assert tick("f1") == ["AMRX"]                     # reviewed FDA sponsor alias, legal suffix removed
    assert tick("f2") == ["TEVA"] and tick("f3") == ["IONS"]
    assert r["e1"]["links"][0]["ticker"] == "D" and r["e1"]["links"][0]["relation"] == "WHOLLY_OWNED_SUBSIDIARY"
    assert r["a2"]["status"] == "COMPANY_UNLINKED" and r["a2"]["unmatched"][0]["reason"] == "JOINT_VENTURE"
    assert r["a3"]["unmatched"][0]["reason"] == "PRIVATE"
    assert {u["reason"] for u in r["t1"]["unmatched"]} == {"LISTED_OUTSIDE_US"}


def test_no_similarity_matching():
    index, _ = fr.load_links()
    assert fr.norm("Boeing Defense, Space & Security") not in index      # a different name is not linked
    assert fr.norm("The Boeing Company") in index and fr.norm("THE BOEING COMPANY.") in index


def test_noise_filtered_general_kept_and_counts():
    rep = report()
    numbers = {x["document_number"] for x in rep["linked"] + rep["company_unlinked"] + rep["general"]}
    assert "noise" not in numbers and "noise2" not in numbers
    assert [g["document_number"] for g in rep["general"]] == ["g1"]
    assert rep["counts"]["linked"] + rep["counts"]["company_unlinked"] + rep["counts"]["general"] == len(numbers)


def test_linked_events_enter_the_catalyst_list_with_neutral_or_risk_labels_only():
    events = cw.fr_catalysts(report())
    by = {(e["symbol"], e["kind"]) for e in events}
    assert ("BA", "FR_AIRWORTHINESS_DIRECTIVE") in by and ("IONS", "FR_PRIORITY_REVIEW_VOUCHER") in by
    assert all(e["match_method"] == "reviewed_issuer_link" and e["source"] == "Federal Register" for e in events)
    assert not any("إيجابي" in fr.KINDS[k][0] for k in fr.KINDS)
    watch = cw.build(None, None, None, NOW, fr=report())
    assert watch["sources"]["federal_register"] is True
    ba = next(e for e in watch["watchlist"] if e["symbol"] == "BA")
    assert "توجيه صلاحية طيران إلزامي (FAA)" in ba["risk_flags"]


def test_faa_title_end_word_and_prv_manufactured_by_sponsor():
    md = doc("Airworthiness Directives; MD Helicopters, LLC Helicopters", FAA, "Rule")
    assert fr.entities(md) == ("FR_AIRWORTHINESS_DIRECTIVE", ["MD Helicopters, LLC"])
    bom = doc("Airworthiness Directives; Bombardier, Inc., Airplanes", FAA, "Rule")
    assert fr.entities(bom)[1] == ["Bombardier, Inc."]
    corr = doc("Airworthiness Directives; The Boeing Company Airplanes; Correction", FAA, "Rule")
    assert fr.entities(corr)[1] == ["The Boeing Company"]
    prv = doc("Issuance of Priority Review Voucher; Rare Pediatric Disease Product; X", FDA)
    body = "FDA has determined that X (y), manufactured by Scholar Rock, Inc., meets the criteria for a voucher."
    assert fr.entities(prv, body) == ("FR_PRIORITY_REVIEW_VOUCHER", ["Scholar Rock, Inc."])
    assert fr.entities(prv, "no sponsor sentence here") == ("FR_PRIORITY_REVIEW_VOUCHER", [])
    index, excluded = fr.load_links()
    assert index[fr.norm("General Electric Company")]["ticker"] == "GE"
    assert excluded[fr.norm("Engine Alliance")]["reason"] == "JOINT_VENTURE"


def test_bad_urls_and_unknown_kinds_are_dropped():
    bad = report()
    bad["linked"][0] = {**bad["linked"][0], "source_url": "https://evil.example/x"}
    assert len(cw.fr_catalysts(bad)) == len(cw.fr_catalysts(report())) - len(report()["linked"][0]["links"])
    assert cw.fr_catalysts({"schema": "other"}) == []
