from __future__ import annotations

from datetime import datetime, timedelta, timezone

from options_radar.external_breakout_shadow import breakout_evidence

AS_OF = datetime(2026, 10, 10, 20, tzinfo=timezone.utc)


def _bars(n: int = 45):
    timestamps = [AS_OF - timedelta(days=n - index) for index in range(n)]
    return [10.0] * n, [9.0] * n, [9.5] * n, [100.0] * n, timestamps


def _valid_kwargs(timestamps):
    return {
        "bar_timestamps": timestamps,
        "as_of": AS_OF,
        "last_bar_complete": True,
        "prices_adjusted": True,
    }


def test_missing_completion_proof_is_fail_closed():
    h, lows, c, v, timestamps = _bars(10)
    result = breakout_evidence(h, lows, c, v, bar_timestamps=timestamps, as_of=AS_OF)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.reasons == ("last_bar_incomplete_or_unverified",)


def test_unadjusted_or_unknown_price_basis_is_rejected():
    h, lows, c, v, timestamps = _bars()
    result = breakout_evidence(
        h, lows, c, v, **{**_valid_kwargs(timestamps), "prices_adjusted": False}
    )
    assert result.status == "INSUFFICIENT_DATA"
    assert result.reasons == ("price_adjustment_unverified",)


def test_missing_or_future_timestamp_is_fail_closed():
    h, lows, c, v, timestamps = _bars()
    future = list(timestamps)
    future[-1] = AS_OF + timedelta(minutes=1)
    result = breakout_evidence(h, lows, c, v, **_valid_kwargs(future))
    assert result.status == "INSUFFICIENT_DATA"
    assert result.reasons == ("timestamp_provenance_or_as_of_invalid",)


def test_non_monotonic_timestamp_is_fail_closed():
    h, lows, c, v, timestamps = _bars()
    timestamps[10], timestamps[11] = timestamps[11], timestamps[10]
    result = breakout_evidence(h, lows, c, v, **_valid_kwargs(timestamps))
    assert result.status == "INSUFFICIENT_DATA"


def test_invalid_ohlc_and_non_numeric_values_are_rejected():
    h, lows, c, v, timestamps = _bars()
    h[-1] = 9.0
    result = breakout_evidence(h, lows, c, v, **_valid_kwargs(timestamps))
    assert result.status == "INVALID_DATA"
    h, lows, c, v, timestamps = _bars()
    v[-1] = "not-a-number"
    result = breakout_evidence(h, lows, c, v, **_valid_kwargs(timestamps))
    assert result.status == "INVALID_DATA"


def test_coiling_is_research_only_after_all_quality_gates():
    h, lows, c, v, timestamps = _bars()
    for i in range(-5, 0):
        h[i], lows[i], c[i] = 10.0, 9.7, 9.9
    result = breakout_evidence(h, lows, c, v, **_valid_kwargs(timestamps))
    assert result.status == "COILING_RESEARCH"
    assert result.research_only is True
    assert "range_contraction" in result.reasons


def test_volume_breakout_is_not_execution_grade():
    h, lows, c, v, timestamps = _bars()
    h[-1], c[-1], v[-1] = 11.0, 10.5, 250.0
    result = breakout_evidence(h, lows, c, v, **_valid_kwargs(timestamps))
    assert result.status == "BREAKOUT_RESEARCH"
    assert result.research_only is True


def test_zero_baseline_volume_is_rejected():
    h, lows, c, v, timestamps = _bars()
    v = [0.0] * len(v)
    result = breakout_evidence(h, lows, c, v, **_valid_kwargs(timestamps))
    assert result.status == "INSUFFICIENT_DATA"
    assert result.reasons == ("missing_volume",)


def test_split_like_raw_history_requires_adjusted_price_proof():
    h, lows, c, v, timestamps = _bars()
    # A raw reverse-split-like discontinuity must not be interpreted as a
    # breakout merely because the caller supplies a clean-looking list.
    h[-1], lows[-1], c[-1] = 100.0, 90.0, 95.0
    result = breakout_evidence(
        h, lows, c, v, **{**_valid_kwargs(timestamps), "prices_adjusted": False}
    )
    assert result.status == "INSUFFICIENT_DATA"
    assert "price_adjustment_unverified" in result.reasons
