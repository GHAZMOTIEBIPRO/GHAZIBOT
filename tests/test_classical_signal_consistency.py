from scripts.send_classical_direction_alerts import _consistent_signal


def _row():
    return {"symbol": "MU", "decision": "CALL", "price": 100.0, "invalidation_level": 98.0, "daily": {"direction": "BULLISH"}, "hourly": {"direction": "BULLISH"}, "intraday": {"direction": "BULLISH", "close": 100.0}}


def test_valid_call():
    assert _consistent_signal(_row())


def test_broken_support():
    row = _row()
    row["invalidation_level"] = 101.0
    assert not _consistent_signal(row)


def test_conflicting_intraday():
    row = _row()
    row["intraday"]["direction"] = "BEARISH"
    assert not _consistent_signal(row)


def test_mismatched_price():
    row = _row()
    row["intraday"]["close"] = 95.0
    assert not _consistent_signal(row)


def test_missing_invalidation():
    row = _row()
    del row["invalidation_level"]
    assert not _consistent_signal(row)


def test_valid_put():
    row = _row()
    row.update(decision="PUT", invalidation_level=102.0)
    for key in ("daily", "hourly", "intraday"):
        row[key]["direction"] = "BEARISH"
    assert _consistent_signal(row)
