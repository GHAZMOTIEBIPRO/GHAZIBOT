from __future__ import annotations

import json

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


def test_retryable_status_retries_then_returns_json(monkeypatch) -> None:
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


def test_forbidden_is_not_retried(monkeypatch) -> None:
    calls: list[int] = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return _response(403, {"message": "Forbidden"})

    monkeypatch.setattr(sec_efts_resilience.requests, "get", fake_get)

    with pytest.raises(requests.HTTPError, match="fallbacks remain active") as exc_info:
        sec_efts_resilience.request_efts_json(
            Settings(),
            {"q": '"merger agreement"'},
            max_attempts=3,
        )

    assert exc_info.value.response is not None
    assert exc_info.value.response.status_code == 403
    assert len(calls) == 1
