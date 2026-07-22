from options_radar.storage import SignalStore


def test_alert_deduplication(tmp_path) -> None:
    store = SignalStore(tmp_path / "signals.sqlite3")
    assert not store.was_alerted("ABC260821C00100000")
    store.mark_alerted("ABC260821C00100000", 82.0, 2.4, "test")
    assert store.was_alerted("ABC260821C00100000")
