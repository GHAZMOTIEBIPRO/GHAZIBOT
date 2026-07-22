from options_radar.universe import _valid_mover_symbol, _valid_symbol


def test_symbol_placeholders_are_rejected() -> None:
    assert _valid_symbol("SYMBOL") is False
    assert _valid_symbol("TICKER") is False
    assert _valid_symbol("NVDA") is True


def test_nasdaq_mover_filter_rejects_warrants_rights_and_units() -> None:
    for symbol in ("APXTW", "PRENW", "ABCDWS", "ABCDU", "ABCDR"):
        assert _valid_mover_symbol(symbol) is False
    assert _valid_mover_symbol("AMD") is True
    assert _valid_mover_symbol("BRK-B") is True
