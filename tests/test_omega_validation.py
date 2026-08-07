from options_radar.omega_validation import build_validation_status


def test_edge_is_not_claimed_without_real_oos():
    result = build_validation_status({})
    assert result["edge_status"] == "EDGE NOT YET PROVEN"
    assert result["oos_status"] == "NOT_RUN"
    assert result["probabilities_calibrated"] is False


def test_calibration_sample_without_time_split_is_not_oos_proof():
    result = build_validation_status({"calibration": {"matured_sample": 500}})
    assert result["edge_status"] == "EDGE NOT YET PROVEN"
    assert result["oos_status"] == "INSUFFICIENT_OR_NOT_TIME_SPLIT"


def test_explicit_time_split_oos_requires_metrics_and_sample():
    result = build_validation_status(
        {
            "calibration": {
                "out_of_sample": {
                    "validated": True,
                    "time_split": True,
                    "sample": 150,
                    "hit_rate": 0.55,
                    "expectancy": 0.12,
                    "drawdown": -0.08,
                }
            }
        }
    )
    assert result["oos_status"] == "VALIDATED_OOS_DATASET"
    assert "EDGE NOT YET PROVEN" not in result["edge_status"]
