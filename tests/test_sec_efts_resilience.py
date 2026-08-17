from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from options_radar import sec_efts_resilience
from options_radar.settings import Settings


def _response(status: int, payload: dict, *, retry_after: str | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "https://efts.sec.gov/LATEST/search-index"
    response._content = json.dumps(payload).encode("utf-8")
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    return response


def _use_temp_circuit(monkeypatch, tmp_path):
    path = tmp_path / "sec_efts_circuit.json"
    monkeypatch.setattr(sec_efts_resilience, "EFTS_CIRCUIT_PATH", path)
    return path


def test_retryable_status_retries_then_returns_json(monkeypatch, tmp_path) -> None:
    circuit_path = _use_temp_circuit(monkeypatch, tmp_path)
    responses = iter(
        [
            _response(429, {"error": "rate limited"}, retry_after="0"),
            _response(200, {"hits": {"hits": []}}),
        ]
    )
    calls: list[int] = []
    sleeps: list[float] = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return next(responses)

    monkeypatch.setattr(sec_efts_resilience.requests, "get", fake_get)
    monkeypatch.setattr(sec_efts_resilience.time, "sleep", sleeps.append)

    payload = sec_efts_resilience.request_efts_json(
        Settings(),
        {"q": '"merger agreement"'},
        max_attempts=3,
    )

    assert payload == {"hits": {"hits": []}}
    assert len(calls) == 2
    assert sleeps == [0.0]
    assert not circuit_path.exists()


def test_forbidden_opens_persistent_circuit_and_is_not_retried(monkeypatch, tmp_path) -> None:
    circuit_path = _use_temp_circuit(monkeypatch, tmp_path)
    calls: list[int] = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return _response(403, {"message": "Forbidden"})

    monkeypatch.setattr(sec_efts_resilience.requests, "get", fake_get)

    with pytest.raises(requests.HTTPError, match="persistent cooldown") as exc_info:
        sec_efts_resilience.request_efts_json(
            Settings(),
            {"q": '"merger agreement"'},
            max_attempts=3,
        )

    assert exc_info.value.response is not None
    assert exc_info.value.response.status_code == 403
    assert len(calls) == 1
    circuit = json.loads(circuit_path.read_text(encoding="utf-8"))
    assert circuit["state"] == "open"
    assert circuit["http_status"] == 403
    assert circuit["consecutive_403"] == 1
    assert circuit["decision_authority"] is False
    assert datetime.fromisoformat(circuit["retry_after"]) > datetime.fromisoformat(circuit["blocked_at"])


def test_open_circuit_skips_http_until_retry_time(monkeypatch, tmp_path) -> None:
    circuit_path = _use_temp_circuit(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    circuit_path.write_text(
        json.dumps(
            {
                "state": "open",
                "http_status": 403,
                "blocked_at": now.isoformat(),
                "retry_after": (now + timedelta(hours=2)).isoformat(),
                "consecutive_403": 2,
            }
        ),
        encoding="utf-8",
    )
    calls: list[int] = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return _response(200, {"hits": {"hits": []}})

    monkeypatch.setattr(sec_efts_resilience.requests, "get", fake_get)

    with pytest.raises(sec_efts_resilience.SecEftsCircuitOpen, match="no HTTP request was sent"):
        sec_efts_resilience.request_efts_json(Settings(), {"q": "test"})

    assert calls == []


def test_expired_circuit_allows_probe_and_closes_on_success(monkeypatch, tmp_path) -> None:
    circuit_path = _use_temp_circuit(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    circuit_path.write_text(
        json.dumps(
            {
                "state": "open",
                "http_status": 403,
                "blocked_at": (now - timedelta(hours=7)).isoformat(),
                "retry_after": (now - timedelta(minutes=1)).isoformat(),
                "consecutive_403": 3,
            }
        ),
        encoding="utf-8",
    )
    calls: list[int] = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return _response(200, {"hits": {"hits": []}})

    monkeypatch.setattr(sec_efts_resilience.requests, "get", fake_get)

    payload = sec_efts_resilience.request_efts_json(Settings(), {"q": "test"}, max_attempts=1)

    assert payload == {"hits": {"hits": []}}
    assert len(calls) == 1
    circuit = json.loads(circuit_path.read_text(encoding="utf-8"))
    assert circuit["state"] == "closed"
    assert circuit["http_status"] == 200
    assert circuit["consecutive_403"] == 0
    assert circuit["decision_authority"] is False
