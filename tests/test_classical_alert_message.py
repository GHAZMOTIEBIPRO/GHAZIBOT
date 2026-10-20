from scripts.send_classical_direction_alerts import _message


def _row(**extra):
    row = {"symbol": "MU", "decision": "CALL", "price": 100.0, "invalidation_level": 98.0,
           "confirmation_level": 101.0, "intraday_bar_closed_at": "2026-10-20T14:45:00+00:00",
           "daily": {"direction": "BULLISH"}, "hourly": {"direction": "BULLISH"},
           "intraday": {"direction": "BULLISH", "close": 100.0},
           "reasons_ar": ["اختراق مقاومة يومية بحجم أعلى من المتوسط"]}
    row.update(extra)
    return row


def test_message_carries_data_time_reason_targets_and_site_link():
    text = _message(_row(targets={"entry": 101.0, "t1": 104.0, "t2": 107.0,
                                  "risk_per_share": 3.0, "t1_reward_to_risk": 1.0}))
    assert "2026-10-20T14:45:00+00:00" in text
    assert "اختراق مقاومة يومية" in text
    assert "T1: <b>$104.00</b>" in text and "T2: <b>$107.00</b>" in text
    assert "عائد/مخاطرة نظري حتى T1: <b>1.00</b> (ليس احتمال وصول)" in text
    assert '<a href="https://ghazibot.vercel.app/?chart=MU">' in text


def test_missing_or_invalid_targets_are_omitted_not_invented():
    assert "T1:" not in _message(_row())
    assert "T1:" not in _message(_row(targets={"entry": 101.0, "t1": None, "t2": 107.0,
                                               "t1_reward_to_risk": 1.2}))


def test_unsafe_symbol_gets_no_link():
    assert "<a href" not in _message(_row(symbol='MU"><script>'))
