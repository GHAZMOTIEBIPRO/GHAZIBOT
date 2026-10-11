from options_radar.external_breakout_shadow import breakout_evidence


def _bars(n=45):
    return [10.0] * n, [9.0] * n, [9.5] * n, [100.0] * n


def test_missing_history_is_fail_closed():
    assert breakout_evidence(*_bars(10)).status == "INSUFFICIENT_DATA"


def test_invalid_ohlc_is_rejected():
    h, l, c, v = _bars()
    h[-1] = 9.0
    assert breakout_evidence(h, l, c, v).status == "INVALID_DATA"


def test_coiling_is_research_only():
    h, l, c, v = _bars()
    for i in range(-5, 0):
        h[i], l[i], c[i] = 10.0, 9.7, 9.9
    result = breakout_evidence(h, l, c, v)
    assert result.status == "COILING_RESEARCH"
    assert result.research_only is True
    assert "range_contraction" in result.reasons


def test_volume_breakout_is_not_execution_grade():
    h, l, c, v = _bars()
    h[-1], c[-1], v[-1] = 11.0, 10.5, 250.0
    result = breakout_evidence(h, l, c, v)
    assert result.status == "BREAKOUT_RESEARCH"
    assert result.research_only is True


def test_zero_baseline_volume_rejected():
    h, l, c, v = _bars()
    v = [0.0] * len(v)
    assert breakout_evidence(h, l, c, v).status == "INSUFFICIENT_DATA"
