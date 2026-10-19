from options_radar.occ_free_context import parse_occ_volume_csv, side_alignment


def test_parse_occ_aggregate_columns():
    parsed = parse_occ_volume_csv("Symbol,Call Volume,Put Volume\nXYZ,12000,8000\n")
    assert parsed["call_volume"] == 12000
    assert parsed["put_volume"] == 8000
    assert parsed["put_call_ratio"] == 0.6667


def test_parse_occ_row_side_layout():
    parsed = parse_occ_volume_csv("P/C,Volume\nC,9000\nP,11000\n")
    assert parsed["call_volume"] == 9000
    assert parsed["put_volume"] == 11000


def test_occ_context_is_small_confirmation_not_flow_proof():
    context = {
        "success": True,
        "call_volume": 15000,
        "put_volume": 10000,
        "report_date": "20260814",
    }
    aligned = side_alignment(context, "call")
    opposed = side_alignment(context, "put")
    assert aligned["aligned"] is True
    assert aligned["bonus"] <= 3
    assert opposed["opposed"] is True
    assert opposed["bonus"] < 0
    assert aligned["context_only"] is True


def test_daily_client_dates_from_actdate_and_excludes_adjusted():
    from types import SimpleNamespace

    from options_radar.occ_free_context import OccDailyVolumeClient

    text = (
        "quantity,underlying,symbol,actype,porc,exchange,actdate\n"
        "500,XYZ,1XYZ,C,C,CBOE,10/16/2026,\n"
        "1200,XYZ,XYZ,C,C,CBOE,10/16/2026,\n"
        "800,XYZ,XYZ,M,P,ISE,10/16/2026,\n"
    )

    class Session:
        def __init__(self):
            self.headers = {}

        def get(self, url, params, timeout):
            return SimpleNamespace(status_code=200, text=text, raise_for_status=lambda: None)

    from datetime import date

    result = OccDailyVolumeClient(session=Session()).fetch("XYZ", reference_date=date(2026, 10, 19))
    assert result["success"] is True
    assert result["report_date"] == "20261016"
    assert result["requested_report_date"] == "20261019"
    assert result["report_date_source"] == "OCC_ACTDATE"
    assert (result["call_volume"], result["put_volume"]) == (1200, 800)
    assert result["nonstandard_rows_excluded"] == 1
