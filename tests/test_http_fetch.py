"""Shared fetch layer: refusal, rate limits, network failure and 304 are separate outcomes."""
from __future__ import annotations

import importlib.util
import io
import sys
import urllib.error
from email.message import Message
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ghazi_http_fetch", Path(__file__).resolve().parents[1] / "options_radar" / "http_fetch.py")
hf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hf  # dataclasses resolve their module by name
_spec.loader.exec_module(hf)


class _Resp:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self.status, self._body = 200, body
        self.headers = Message()
        for k, v in headers.items():
            self.headers[k] = v

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    msg = Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("https://x.test/a", code, "err", msg, io.BytesIO(b"secret body"))


class _Opener:
    def __init__(self, *events):
        self.events, self.calls, self.requests = list(events), 0, []

    def __call__(self, request, timeout):
        self.calls += 1
        self.requests.append(request)
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


def _run(opener, **kw):
    sleeps: list[float] = []
    hf._last_call.clear()
    kw.setdefault("min_interval", 0)
    result = hf.fetch("https://x.test/a", opener=opener, sleep=sleeps.append, clock=lambda: 0.0, **kw)
    return result, sleeps


def test_ok_keeps_body_and_validators():
    opener = _Opener(_Resp(b"a,b\n1,2", {"Last-Modified": "Wed, 28 Oct 2026 19:50:59 GMT", "ETag": '"x1"'}))
    r, _ = _run(opener)
    assert r.ok and r.body == b"a,b\n1,2" and r.last_modified.startswith("Wed, 28 Oct")
    assert r.etag == '"x1"' and r.attempts == 1


def test_refusal_is_not_retried_and_never_carries_the_body():
    opener = _Opener(_http_error(403))
    r, _ = _run(opener, attempts=4)
    assert r.outcome == "REFUSED" and r.http == 403 and opener.calls == 1
    assert r.body == b"" and r.status() == "REFUSED_HTTP_403"


def test_not_found_is_its_own_outcome():
    r, _ = _run(_Opener(_http_error(404)))
    assert r.outcome == "NOT_FOUND"


def test_network_failure_retries_with_bounded_backoff_then_reports():
    opener = _Opener(*(urllib.error.URLError("reset") for _ in range(3)))
    r, sleeps = _run(opener, attempts=3)
    assert r.outcome == "NETWORK_ERROR" and r.http is None and opener.calls == 3
    assert sleeps == [1, 2]


def test_server_error_then_success():
    opener = _Opener(_http_error(503), _Resp(b"ok", {}))
    r, _ = _run(opener)
    assert r.ok and r.attempts == 2


def test_rate_limit_waits_retry_after_capped_and_retries_once():
    opener = _Opener(_http_error(429, {"Retry-After": "600"}), _http_error(429))
    r, sleeps = _run(opener, max_retry_after=20)
    assert r.outcome == "RATE_LIMITED" and opener.calls == 2 and sleeps[0] == 20


def test_conditional_get_sends_validators_and_reports_not_modified():
    opener = _Opener(_http_error(304))
    r, _ = _run(opener, if_modified_since="Wed, 28 Oct 2026 19:50:59 GMT", etag='"x1"')
    req = opener.requests[0]
    assert r.outcome == "NOT_MODIFIED"
    assert req.get_header("If-modified-since") == "Wed, 28 Oct 2026 19:50:59 GMT"
    assert req.get_header("If-none-match") == '"x1"'


def test_requests_to_one_host_are_spaced():
    sleeps: list[float] = []
    hf._last_call.clear()
    hf._last_call["x.test"] = 10.0
    hf.fetch("https://x.test/b", opener=_Opener(_Resp(b"", {})), sleep=sleeps.append, clock=lambda: 10.4,
             min_interval=1.0)
    assert abs(sleeps[0] - 0.6) < 1e-9
