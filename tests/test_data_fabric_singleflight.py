from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from options_radar.data_fabric_singleflight import SingleFlightGroup


def test_concurrent_identical_calls_execute_loader_once_and_clone_results() -> None:
    group = SingleFlightGroup()
    started = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    calls = 0

    def loader() -> dict[str, list[int]]:
        nonlocal calls
        with lock:
            calls += 1
        started.set()
        assert release.wait(timeout=2)
        return {"rows": [1, 2, 3]}

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(group.do, ("option_chain", "XYZ"), loader)
        assert started.wait(timeout=2)
        second = executor.submit(group.do, ("option_chain", "XYZ"), loader)
        release.set()
        first_result, first_shared = first.result(timeout=2)
        second_result, second_shared = second.result(timeout=2)

    assert calls == 1
    assert sorted((first_shared, second_shared)) == [False, True]
    assert first_result == second_result == {"rows": [1, 2, 3]}
    assert first_result is not second_result
    assert first_result["rows"] is not second_result["rows"]

    first_result["rows"].append(99)
    assert second_result["rows"] == [1, 2, 3]
    assert group.in_flight_count() == 0


def test_completed_call_is_never_cached() -> None:
    group = SingleFlightGroup()
    calls = 0

    def loader() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"sequence": calls}

    first, first_shared = group.do(("stock_bars", "XYZ"), loader)
    second, second_shared = group.do(("stock_bars", "XYZ"), loader)

    assert calls == 2
    assert first == {"sequence": 1}
    assert second == {"sequence": 2}
    assert first_shared is False
    assert second_shared is False


def test_failed_flight_is_not_cached_and_followers_receive_failure() -> None:
    group = SingleFlightGroup()
    started = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    calls = 0

    def failing_loader() -> dict[str, int]:
        nonlocal calls
        with lock:
            calls += 1
        started.set()
        assert release.wait(timeout=2)
        raise RuntimeError("provider unavailable")

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(group.do, ("stock_bars", "ERR"), failing_loader)
        assert started.wait(timeout=2)
        second = executor.submit(group.do, ("stock_bars", "ERR"), failing_loader)
        release.set()
        with pytest.raises(RuntimeError, match="provider unavailable"):
            first.result(timeout=2)
        with pytest.raises(RuntimeError, match="provider unavailable"):
            second.result(timeout=2)

    assert calls == 1
    assert group.in_flight_count() == 0

    recovered, shared = group.do(
        ("stock_bars", "ERR"),
        lambda: {"sequence": 2},
    )
    assert recovered == {"sequence": 2}
    assert shared is False


def test_stock_and_options_fabric_entrypoints_install_singleflight_after_fabric() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "scripts/run_options_radar_fabric.py",
        "scripts/fast_explosion_scan_fabric.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "install_data_fabric()" in text
        assert "install_data_fabric_singleflight()" in text
        assert text.index("install_data_fabric()") < text.index("install_data_fabric_singleflight()")
