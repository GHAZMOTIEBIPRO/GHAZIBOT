from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from scripts import build_catalyst_watchlist as watch
from scripts import build_clinical_registry_feed as registry
from scripts import send_catalyst_watchlist_alerts as alerts

NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
INDEX = registry._names.build_name_index({"MRNA": "Moderna Inc"})


def study():
    return {"hasResults": True, "protocolSection": {
        "identificationModule": {"nctId": "NCT12345678", "briefTitle": "Example trial"},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Moderna Inc", "class": "INDUSTRY"}},
        "statusModule": {"overallStatus": "COMPLETED",
                         "lastUpdatePostDateStruct": {"date": "2026-10-21", "type": "ACTUAL"},
                         "resultsFirstPostDateStruct": {"date": "2026-10-20", "type": "ACTUAL"}},
    }}


def feed(rows=None):
    return registry.collect(INDEX, now=NOW, fetch=lambda _: {"studies": [study()] if rows is None else rows})


def test_live_schema_flows_to_watch_site_feed_and_telegram_without_direction():
    report = feed()
    assert report["status"] == "OK" and report["coverage_complete"]
    out = watch.build(None, None, None, NOW, report)
    item = out["watchlist"][0]
    assert item["symbol"] == "MRNA" and not item["price_confirmed_signal"]
    event = item["catalysts"][0]
    assert event["date"] == "2026-10-20"  # results publication, not retrieval/update
    assert event["outcome_direction"] == "NOT_INFERRED"
    picks = alerts.candidates(out, now=NOW)
    assert len(picks) == len(alerts.daily_brief_candidates(out, now=NOW)) == 1
    assert "لا يثبت نجاح العلاج" in alerts.message(picks[0])
    assert "National Library of Medicine" in alerts.daily_brief_message(out, alerts.daily_brief_candidates(out, now=NOW), now=NOW)
    _, first = alerts.run(out, {"schema": alerts.SCHEMA, "seen": {}}, now=NOW, send=lambda _: 123)
    assert first["sent"] == 1


@pytest.mark.parametrize("change", ["future", "bad_id", "collaborator", "ambiguous", "fuzzy", "bad_shape"])
def test_unverifiable_identity_dates_and_shapes_do_not_map(change):
    row = study()
    p = row["protocolSection"]
    index = INDEX
    if change == "future":
        p["statusModule"]["lastUpdatePostDateStruct"]["date"] = "2026-10-23"
    elif change == "bad_id":
        p["identificationModule"]["nctId"] = "NCT12345678?evil"
    elif change == "collaborator":
        p["sponsorCollaboratorsModule"] = {"leadSponsor": {"name": "Unknown", "class": "INDUSTRY"},
                                           "collaborators": [{"name": "Moderna"}]}
    elif change == "ambiguous":
        index = registry._names.build_name_index({"MRNA": "Moderna Inc", "OTHER": "Moderna Corp"})
    elif change == "fuzzy":
        p["sponsorCollaboratorsModule"]["leadSponsor"]["name"] = "Moderna unrelated research"
    else:
        p["statusModule"] = "malformed"
    assert registry.collect(index, now=NOW, fetch=lambda _: {"studies": [row]})["events"] == []


def test_status_observation_is_not_a_new_failure_or_results_without_evidence():
    row = study()
    row["hasResults"] = False
    row["protocolSection"]["statusModule"]["overallStatus"] = "TERMINATED"
    event = feed([row])["events"][0]
    assert event["kind"] == "TRIAL_STATUS_REVIEW"
    assert "تاريخ تغير الحالة" in event["label"]
    assert event["date"] == "2026-10-21"


def test_bounded_partial_pagination_and_failures_are_explicit():
    calls = []
    def fetch(params):
        calls.append(params)
        return {"studies": [study()], "nextPageToken": str(len(calls))}
    out = registry.collect(INDEX, now=NOW, fetch=fetch, max_pages=999)
    assert len(calls) == 3 and out["status"] == "PARTIAL"
    assert not out["coverage_complete"] and len(out["events"]) == 1
    def failed(_):
        raise OSError("secret server text")
    out = registry.collect(INDEX, now=NOW, fetch=failed)
    assert out["status"] == "UNAVAILABLE" and out["events"] == []
    assert out["error"] == "OSError" and "secret" not in str(out)
    assert registry.collect(INDEX, now=NOW, fetch=lambda _: {})["status"] == "UNAVAILABLE"


def test_fresh_empty_source_is_available_stale_source_is_not():
    report = feed([])
    assert watch.build(None, None, None, NOW, report)["sources"]["clinicaltrials"] is True
    report["generated_at"] = (NOW - timedelta(days=4)).isoformat()
    assert watch.build(None, None, None, NOW, report)["sources"]["clinicaltrials"] is False


@pytest.mark.parametrize("field,value", [("outcome_direction", "bullish"), ("official_registry_only", False),
                                         ("source_url", "https://clinicaltrials.gov.evil/study/NCT12345678"),
                                         ("match_method", "fuzzy")])
def test_watch_and_bot_reject_inconsistent_registry_evidence(field, value):
    report = feed()
    forged = deepcopy(report)
    forged["events"][0][field] = value
    assert watch.build(None, None, None, NOW, forged)["watchlist"] == []
    out = watch.build(None, None, None, NOW, report)
    out["watchlist"][0]["catalysts"][0][field] = value
    assert alerts.candidates(out, now=NOW) == []
    assert alerts.daily_brief_candidates(out, now=NOW) == []


def test_nonfinite_prices_never_confirm_price_band():
    for price in (float("nan"), float("inf")):
        result = watch.price_band("MRNA", {"quotes": {"MRNA": {
            "price": price, "quote_time": NOW.isoformat(), "public_display_permitted": True}}}, NOW)
        assert result["price_band"] == "UNVERIFIED"
