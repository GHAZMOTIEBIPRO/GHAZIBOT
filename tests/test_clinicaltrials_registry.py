from __future__ import annotations

from datetime import date

from options_radar.clinicaltrials_registry import scan_recent_clinicaltrials


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return _Response(self.payload)


def _study(*, sponsor="ModernaTX, Inc.", results=True, status="COMPLETED"):
    today = date.today().isoformat()
    status_module = {
        "overallStatus": status,
        "lastUpdatePostDateStruct": {"date": today},
    }
    if results:
        status_module["resultsFirstPostDateStruct"] = {"date": today}
    return {
        "hasResults": results,
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT12345678",
                "briefTitle": "A Study of Example Therapy",
            },
            "statusModule": status_module,
            "sponsorCollaboratorsModule": {
                "leadSponsor": {
                    "name": sponsor,
                    "class": "INDUSTRY",
                }
            },
            "designModule": {"phases": ["PHASE3"]},
        },
    }


def test_recent_results_posted_maps_official_registry_to_ticker_without_direction_claim():
    session = _Session({"studies": [_study()]})
    events = scan_recent_clinicaltrials(
        session=session,
        allowed_symbols={"MRNA"},
        company_names={"MRNA": "Moderna Inc"},
        lookback_days=7,
    )

    assert len(events) == 1
    event = events[0]
    assert event["symbol"] == "MRNA"
    assert event["source"] == "ClinicalTrials.gov"
    assert event["form"] == "REGISTRY_RESULTS"
    assert event["score"] == 10
    assert "direction is not inferred" in event["evidence"]
    assert session.calls[0]["params"]["query.term"].startswith(
        "AREA[LeadSponsorClass]INDUSTRY"
    )


def test_terminated_registry_status_is_negative_attention_not_failed_trial_claim():
    session = _Session(
        {
            "studies": [
                _study(results=False, status="TERMINATED"),
            ]
        }
    )
    events = scan_recent_clinicaltrials(
        session=session,
        allowed_symbols={"MRNA"},
        company_names={"MRNA": "Moderna Inc"},
        lookback_days=7,
    )

    assert len(events) == 1
    event = events[0]
    assert event["form"] == "REGISTRY_STATUS"
    assert event["score"] == -8
    assert "reason/effect on efficacy is not inferred" in event["evidence"]


def test_unmatched_industry_sponsor_is_ignored():
    session = _Session({"studies": [_study(sponsor="Unrelated Pharma LLC")]})
    events = scan_recent_clinicaltrials(
        session=session,
        allowed_symbols={"MRNA"},
        company_names={"MRNA": "Moderna Inc"},
        lookback_days=7,
    )

    assert events == []
