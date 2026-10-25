"""The test session itself must not touch the network or tracked runtime data."""
import os
import socket
from pathlib import Path

import pytest

from options_radar import phase60_sources

ROOT = Path(__file__).resolve().parents[1]


def test_outbound_connections_are_refused():
    with socket.socket() as sock, pytest.raises(RuntimeError, match="network access in a unit test"):
        sock.connect(("203.0.113.1", 443))  # TEST-NET-3, never routed


def test_runtime_state_paths_are_outside_the_repository():
    for name in ("GHAZI_SOURCE_AUDIT_PATH", "FAST_MARKET_STATE_PATH", "DATA_FABRIC_HEALTH_PATH"):
        assert ROOT not in Path(os.environ[name]).resolve().parents
    assert ROOT not in phase60_sources._AUDIT_PATH.resolve().parents
