from options_radar.stream_gateway import configured_stream_symbols


def test_stream_gateway_dedupes_and_caps_symbols(monkeypatch):
    stocks = ",".join([f"S{index}" for index in range(40)] + ["S1"])
    options = ",".join([f"OPT{index}" for index in range(230)] + ["OPT1"])
    monkeypatch.setenv("STREAM_STOCK_SYMBOLS", stocks)
    monkeypatch.setenv("STREAM_OPTION_CONTRACTS", options)
    stock_symbols, option_contracts = configured_stream_symbols()
    assert len(stock_symbols) == 30
    assert len(option_contracts) == 200
    assert len(stock_symbols) == len(set(stock_symbols))
    assert len(option_contracts) == len(set(option_contracts))
