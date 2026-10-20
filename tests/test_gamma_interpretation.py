from datetime import datetime, timezone

from options_radar.free_gex_validation import next_session_of
from options_radar.gamma_interpretation import history_entry, interpret, validate_levels

ENGINE = {"available": True, "spot": 7690.73, "net_gex": -28.9, "gamma_flip": 7760.8,
          "call_wall": 7800.0, "put_wall": 7700.0, "gamma_regime": "negative", "gci": 0.056,
          "zdte_share_abs_gex": 0.31, "front_expiry": "2026-10-20", "expirations_used": 4}


def test_interpretation_labels_model_outputs_and_negative_regime():
    out = interpret(ENGINE)
    assert out["is_measured_dealer_position"] is False
    assert out["hedging_direction_model"] == "AMPLIFYING"
    assert out["hedging_pressure_bn_per_1pct"] == 28.9
    assert out["distance_pct"]["call_wall"] == round((7800 / 7690.73 - 1) * 100, 2)
    text = " ".join(out["reading_ar"])
    assert "تحت نقطة الانقلاب" in text and "ليس سقفًا مضمونًا" in text
    # Spot is below the put wall here, so the walls are not a valid range now.
    assert "ليس بين الجدارين" in text
    assert "gamma flip" in out["model_outputs"]


def test_positive_regime_dampens_and_unavailable_engine_returns_none():
    out = interpret({**ENGINE, "spot": 7750, "gamma_flip": 7700, "net_gex": 12.0, "put_wall": 7650})
    assert out["hedging_direction_model"] == "DAMPENING"
    assert "فوق نقطة الانقلاب" in out["reading_ar"][0]
    assert interpret({"available": False}) is None and interpret({**ENGINE, "spot": None}) is None


def _snap(stamp, spot, put_wall, call_wall, regime="positive"):
    return {"engine_levels": history_entry(
        {**ENGINE, "spot": spot, "put_wall": put_wall, "call_wall": call_wall, "gamma_regime": regime},
        stamp)}


def test_forward_test_uses_last_snapshot_before_session_and_naive_band_baseline():
    session = lambda t: "2026-10-20" if t.hour < 13 else "2026-10-21"
    history = [
        _snap("2026-10-20T04:00:00+00:00", 7700, 7600, 7900),   # superseded below
        _snap("2026-10-20T12:00:00+00:00", 7700, 7650, 7800),   # last before 10-20
        _snap("2026-10-20T20:00:00+00:00", 7700, 7690, 7710, "negative"),  # for 10-21
        {"engine_levels": None},
    ]
    bars = [{"time": "2026-10-20", "high": 7760, "low": 7660},
            {"time": "2026-10-21", "high": 7790, "low": 7600}]
    out = validate_levels(history, bars, session)
    assert out["sessions_tested"] == 2
    # 10-20: walls 7650-7800 contain 7660-7760; centred band 7625-7775 also contains it.
    # 10-21: neither contains 7600-7790.
    assert out["walls_contained_range_rate"] == 0.5
    assert out["same_width_centred_band_rate"] == 0.5
    assert out["regime_sessions"] == {"positive": 1, "negative": 1}
    assert out["verdict"] == "INSUFFICIENT_SAMPLE"


def test_next_session_skips_sessions_already_open():
    pre = datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)       # Tue, before open
    during = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)   # Tue, market open
    friday_night = datetime(2026, 10, 23, 22, 0, tzinfo=timezone.utc)
    assert next_session_of(pre) == "2026-10-20"
    assert next_session_of(during) == "2026-10-21"
    assert next_session_of(friday_night) == "2026-10-26"
