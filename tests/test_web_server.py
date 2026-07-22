from __future__ import annotations

from pathlib import Path

import pytest

import main


class FakeServer:
    created_address: tuple[str, int] | None = None
    served = False
    closed = False

    def __init__(self, address, handler):
        type(self).created_address = address
        self.handler = handler

    def serve_forever(self):
        type(self).served = True

    def server_close(self):
        type(self).closed = True


def test_serve_dashboard_binds_render_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "12345")
    monkeypatch.setattr(main, "ThreadingHTTPServer", FakeServer)

    assert main.serve_dashboard() == 0
    assert FakeServer.created_address == ("0.0.0.0", 12345)
    assert FakeServer.served is True
    assert FakeServer.closed is True


def test_serve_dashboard_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "not-a-number")
    with pytest.raises(ValueError, match="PORT must be an integer"):
        main.serve_dashboard()


def test_procfile_declares_web_process() -> None:
    assert Path("Procfile").read_text(encoding="utf-8").strip() == "web: python main.py"
