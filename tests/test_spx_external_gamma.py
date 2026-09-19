from options_radar.spx_external_gamma import _distance_pct


def test_distance_pct():
    assert _distance_pct(7600, 7600) == 0.0
    assert _distance_pct(7600, 7700) > 0
    assert _distance_pct(7600, 7500) < 0
    assert _distance_pct(0, 7600) is None
