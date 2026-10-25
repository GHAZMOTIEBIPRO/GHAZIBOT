"""Hermetic test session.

- Runtime state paths point at a temporary directory, so tests never write
  into the tracked data/ or state/ trees.
- Outbound connections are refused unless a test is marked ``network``;
  a unit test that silently reaches a provider is a bug (and may break a
  provider's terms).
- The session fails if any tracked file under data/ or state/ changed.
"""
from __future__ import annotations

import os
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_RUNTIME = Path(tempfile.mkdtemp(prefix="ghazi-test-runtime-"))
# Set before any test module imports the code that reads them.
os.environ.setdefault("GHAZI_SOURCE_AUDIT_PATH", str(_RUNTIME / "source_audit.json"))
os.environ.setdefault("FAST_MARKET_STATE_PATH", str(_RUNTIME / "fast_market_state.json"))
os.environ.setdefault("DATA_FABRIC_HEALTH_PATH", str(_RUNTIME / "provider_health.json"))

_GUARDED = ("data", "state")
_real_connect = socket.socket.connect
# Clients that do not use Python sockets (libcurl via curl_cffi, used by
# yfinance) still honour proxy variables; a dead local proxy stops them.
_PROXY_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")
_DEAD_PROXY = "http://127.0.0.1:9"
_ORIGINAL_PROXY = {k: os.environ.get(k) for k in _PROXY_VARS + ("NO_PROXY", "no_proxy")}


def _tracked_changes() -> set[str]:
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", *_GUARDED], cwd=ROOT,
                             capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line for line in out.splitlines() if line and not line.startswith("??")}


def pytest_sessionstart(session):
    session.config._ghazi_tracked_before = _tracked_changes()


def pytest_sessionfinish(session, exitstatus):
    before = getattr(session.config, "_ghazi_tracked_before", set())
    changed = _tracked_changes() - before
    if changed:
        print("\nTests modified tracked runtime data:\n  " + "\n  ".join(sorted(changed)))
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _local(address) -> bool:
    host = address[0] if isinstance(address, tuple) else address
    return not isinstance(host, str) or host in ("localhost", "::1") or host.startswith("127.")


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if request.node.get_closest_marker("network"):
        for key, value in _ORIGINAL_PROXY.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        return
    for key in _PROXY_VARS:
        monkeypatch.setenv(key, _DEAD_PROXY)
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")

    def guarded(self, address):
        if self.family == socket.AF_UNIX or _local(address):
            return _real_connect(self, address)
        raise RuntimeError(f"network access in a unit test: {address!r} (mark the test 'network')")

    monkeypatch.setattr(socket.socket, "connect", guarded)
