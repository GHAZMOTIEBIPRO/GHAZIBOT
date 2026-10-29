from __future__ import annotations

import importlib.util
import json
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
    # A joint venture links to its U.S.-listed partner as INDIRECT exposure, with its documented share;
    # the effect on that partner is not inferred from the link.
    jv = r["a2"]["links"]
    assert [x["ticker"] for x in jv] == ["GE"] and jv[0]["relation"] == "JOINT_VENTURE_PARTNER"
    assert jv[0]["exposure"] == "INDIRECT" and jv[0]["ownership_share"] == 0.5 and jv[0]["interpretation_confidence"] == "MEDIUM"
    assert r["a2"]["potential_impact"] == "NEEDS_IMPACT_ASSESSMENT"
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
    assert index[fr.norm("General Electric Company")][0]["ticker"] == "GE"
    # Engine Alliance (GE + Pratt & Whitney): a documented joint venture, linked only once its evidence passed.
    if fr.norm("Engine Alliance") in index:
        assert sorted(x["ticker"] for x in index[fr.norm("Engine Alliance")]) == ["GE", "RTX"]
    else:
        assert excluded[fr.norm("Engine Alliance")]["reason"] == "EVIDENCE_PENDING"
    # Scholar Rock: no evidence page passed, so the subsidiary is not linked to SRRK.
    assert fr.norm("Scholar Rock, Inc.") not in index
    assert excluded[fr.norm("Scholar Rock, Inc.")]["reason"] == "OWNERSHIP_NOT_VERIFIED"


def test_a_reviewed_row_is_used_only_after_its_evidence_check_passed(tmp_path):
    table = {"links": [
        {"names": ["Alpha Corp"], "ticker": "ALP", "relation": "SAME_ENTITY", "evidence_verified_run": 1},
        {"names": ["Beta Corp"], "ticker": "BET", "relation": "SAME_ENTITY"}], "excluded": []}
    path = tmp_path / "links.json"
    path.write_text(json.dumps(table), encoding="utf-8")
    index, excluded = fr.load_links(path)
    assert index[fr.norm("Alpha Corp")][0]["ticker"] == "ALP"
    assert fr.norm("Beta Corp") not in index and excluded[fr.norm("Beta Corp")]["reason"] == "EVIDENCE_PENDING"
    # Shipped rows still awaiting their evidence check are never in the index.
    shipped = json.loads((ROOT / "data" / "issuer_links.json").read_text(encoding="utf-8"))
    live, _ = fr.load_links()
    for row in shipped["links"]:
        if not isinstance(row.get("evidence_verified_run"), int):
            assert not any(r is row or r.get("ticker") == row["ticker"] and r.get("legal_entity") == row["legal_entity"]
                           for r in live.get(fr.norm(row["names"][0]), [])), row["names"][0]


def test_bad_urls_and_unknown_kinds_are_dropped():
    bad = report()
    bad["linked"][0] = {**bad["linked"][0], "source_url": "https://evil.example/x"}
    assert len(cw.fr_catalysts(bad)) == len(cw.fr_catalysts(report())) - len(report()["linked"][0]["links"])
    assert cw.fr_catalysts({"schema": "other"}) == []


def _links(tmp_path, links, excluded=()):
    path = tmp_path / "links.json"
    path.write_text(json.dumps({"links": links, "excluded": list(excluded)}), encoding="utf-8")
    return fr.load_links(path)


def test_ownership_changes_over_time_link_only_inside_the_validity_window(tmp_path):
    src = "https://example.gov/sale"
    row = {"legal_entity": "Gamma Aero LLC", "relation": "WHOLLY_OWNED_SUBSIDIARY", "validity_source": src,
           "evidence_url": src, "evidence_verified_run": 1}
    index, excluded = _links(tmp_path, [
        {**row, "names": ["Gamma Aero"], "ticker": "OLDP", "valid_to": "2026-06-30"},
        {**row, "names": ["Gamma Aero"], "ticker": "NEWP", "valid_from": "2026-07-01"},
        {**row, "names": ["Delta Systems"], "legal_entity": "Delta Systems Inc", "ticker": "DLT", "valid_from": "2026-11-01"}])
    title = "Airworthiness Directives; {} Airplanes"
    before = fr.classify(doc(title.format("Gamma Aero"), FAA, day="2026-05-01"), index, excluded)
    after = fr.classify(doc(title.format("Gamma Aero"), FAA, day="2026-10-27"), index, excluded)
    early = fr.classify(doc(title.format("Delta Systems"), FAA, day="2026-10-27"), index, excluded)
    assert [x["ticker"] for x in before["links"]] == ["OLDP"]       # the owner at the document's date
    assert [x["ticker"] for x in after["links"]] == ["NEWP"]
    assert early["status"] == "COMPANY_UNLINKED" and early["unmatched"][0]["reason"] == "OUTSIDE_RELATION_VALIDITY"


def test_a_parent_or_partner_links_only_with_a_documented_dated_relation_and_bad_rows_fail(tmp_path):
    url = "https://x.example"
    table = {"links": [
        # documented parent: band, check date and source -> links, as indirect exposure
        {"names": ["Omega Holdings"], "legal_entity": "Omega Holdings", "ticker": "OMG", "relation": "PARENT_OF_LISTED_COMPANY",
         "ownership_band": "CONTROLLING_PARENT", "relation_as_of": "2026-10-29", "validity_source": url,
         "evidence_url": url, "evidence_verified_run": 1},
        # undocumented joint venture: no band, no date -> validation errors, and never linked
        {"names": ["Sigma JV"], "legal_entity": "Sigma JV LLC", "ticker": "SIG", "relation": "JOINT_VENTURE_PARTNER",
         "ownership_share": 1.5, "evidence_url": url},
        {"names": ["Kappa"], "legal_entity": "Kappa Inc", "ticker": "KAP", "relation": "SAME_ENTITY",
         "valid_from": "2026-13", "evidence_url": url},
        {"names": ["Lambda"], "legal_entity": "Lambda Inc", "ticker": "LAM", "relation": "SAME_ENTITY",
         "valid_from": "2026-09-01", "valid_to": "2026-01-01", "validity_source": url, "evidence_url": url}],
        "excluded": [{"names": ["Tau"], "reason": "LOOKS_SIMILAR"}]}
    errors = fr.validate_links(table)
    assert not any("OMG" in e for e in errors)
    assert any("SIG" in e and "ownership_band" in e for e in errors) and any("SIG" in e and "relation_as_of" in e for e in errors)
    assert any("SIG" in e and "fraction" in e for e in errors)
    assert any("valid_from must be" in e for e in errors) and any("needs validity_source" in e for e in errors)
    assert any("after valid_to" in e for e in errors) and any("LOOKS_SIMILAR" in e for e in errors)
    index, excluded = _links(tmp_path, table["links"], table["excluded"])
    title = "Airworthiness Directives; Omega Holdings Airplanes"
    parent = fr.classify(doc(title, FAA), index, excluded)["links"][0]
    assert parent["ticker"] == "OMG" and parent["exposure"] == "INDIRECT" and parent["interpretation_confidence"] == "MEDIUM"
    assert fr.norm("Sigma JV") not in index                       # no evidence run: pending, never linked
    shipped = json.loads((ROOT / "data" / "issuer_links.json").read_text(encoding="utf-8"))
    assert fr.validate_links(shipped) == []


def test_document_type_entity_impact_importance_and_confidence_are_separate():
    r = {x["document_number"]: x for x in report()["linked"]}
    ad = r["a1"]
    assert ad["document_type"] == "FR_AIRWORTHINESS_DIRECTIVE" and ad["importance_basis"] == "DOCUMENT_TYPE"
    # an FAA directive is not by itself materially negative: the impact stays unassessed
    assert ad["potential_impact"] == "NEEDS_IMPACT_ASSESSMENT" and ad["potential_impact_ar"] == "يحتاج تقييم الأثر"
    link = ad["links"][0]
    assert link["name_basis"] == "LEGAL_NAME" and link["interpretation_confidence"] == "HIGH"
    assert r["f3"]["links"][0]["interpretation_confidence"] == "MEDIUM"      # sponsor read from the body
    ba = next(x for x in cw.fr_catalysts(report()) if x["symbol"] == "BA")
    assert ba["potential_impact"] == "NEEDS_IMPACT_ASSESSMENT" and ba["interpretation_confidence"] == "HIGH"
