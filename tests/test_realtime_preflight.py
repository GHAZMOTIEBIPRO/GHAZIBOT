from __future__ import annotations

from scripts import preflight_intrinio_realtime as preflight


def test_missing_key_is_not_ready() -> None:
    report = preflight.run_preflight("")
    assert report["status"] == "NOT_READY"
    assert report["reason"] == "missing_intrinio_api_key"
    assert report["api_key_present"] is False


def test_auth_denied_stops_before_websocket(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "authenticate_realtime", lambda _key: (403, ""))

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("websocket probe must not run after denied auth")

    monkeypatch.setattr(preflight, "probe_websocket", should_not_run)
    report = preflight.run_preflight("secret")
    assert report["status"] == "NOT_READY"
    assert report["auth_http_status"] == 403
    assert report["reason"] == "realtime_auth_http_403"


def test_auth_and_websocket_open_are_ready(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "authenticate_realtime", lambda _key: (200, "opaque-token"))
    monkeypatch.setattr(
        preflight,
        "probe_websocket",
        lambda _token, timeout=12.0: {
            "opened": True,
            "error": None,
            "close_code": 1000,
            "elapsed_seconds": 0.25,
        },
    )
    report = preflight.run_preflight("secret")
    assert report["status"] == "READY"
    assert report["auth_ok"] is True
    assert report["websocket_open"] is True
    assert report["reason"] == "realtime_opra_auth_and_websocket_ok"


def test_websocket_failure_is_not_ready(monkeypatch) -> None:
    monkeypatch.setattr(preflight, "authenticate_realtime", lambda _key: (200, "opaque-token"))
    monkeypatch.setattr(
        preflight,
        "probe_websocket",
        lambda _token, timeout=12.0: {
            "opened": False,
            "error": "WebSocketBadStatusException",
            "close_code": None,
            "elapsed_seconds": 0.5,
        },
    )
    report = preflight.run_preflight("secret")
    assert report["status"] == "NOT_READY"
    assert report["auth_ok"] is True
    assert report["websocket_open"] is False
    assert report["reason"] == "realtime_websocket_not_open"
