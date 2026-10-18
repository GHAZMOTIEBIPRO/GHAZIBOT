"""SPX Gamma research must reject expired GitHub snapshots and zero-option payloads."""
import csv
import io
import json
from datetime import datetime, timezone

from options_radar import free_gex_validation as gex

NOW = datetime(2026, 10, 18, 15, tzinfo=timezone.utc)


def test_github_daily_gamma_uses_observation_date_not_generated_time(monkeypatch):
    def source(day):
        monkeypatch.setattr(gex, "get", lambda url: json.dumps({
            "date":day,"symbol":"SPX","spot":7744,
            "net_gex_dollars":-100_000,"zero_gamma_flip":7740,
        }).encode())
        return gex.fetch_json_source("dhawalc/spx-gamma-levels", "url", now=NOW)

    good=source("2026-10-16")
    assert good["available"] is True
    assert good["quote_timestamp_verified"] is False
    assert good["source_observation_date"] == "2026-10-16"
    for old in ("2026-10-01", "2026-10-19", "malformed"):
        assert source(old)["available"] is False


def test_archive_gamma_expiry_and_empty_numeric_fields_are_not_fabricated(monkeypatch):
    header=["date","time","spot","net_0dte_gex","gamma_flip_proxy"]
    def archive(day):
        output=io.StringIO()
        writer=csv.DictWriter(output,fieldnames=header)
        writer.writeheader()
        writer.writerow({"date":day,"time":"12:15","spot":"7700",
                         "net_0dte_gex":"","gamma_flip_proxy":""})
        monkeypatch.setattr(gex,"get",lambda url:output.getvalue().encode())
        return gex.fetch_archive("url",now=NOW)
    assert archive("2026-10-16")["available"] is True
    stale=archive("2026-10-01")
    assert stale["available"] is False
    assert stale["gex"] is None
    assert gex.compare_metric([stale],"gex")["count"]==0


def test_cboe_requires_actual_spxw_contracts_and_valid_spot(monkeypatch):
    def snap(options,spot=7700):
        monkeypatch.setattr(gex,"get",lambda url:json.dumps({
            "data":{"options":options,"current_price":spot}
        }).encode())
        return gex.fetch_cboe("url")
    assert snap([])["available"] is False
    assert snap([{"option":"SPY_TEST"}])["available"] is False
    good=snap([{"option":"SPXW260920C07700000"}])
    assert good["available"] is True
    assert good["quote_timestamp_verified"] is False
    assert snap([{"option":"SPXW260920C07700000"}],spot=0)["available"] is False


def test_gamma_quorum_absent_when_only_one_numerical_source_exists():
    rows=[
        {"available":True,"gex":-1000},
        {"available":False,"gex":5000},
        {"available":True,"gex":None},
    ]
    result=gex.compare_metric(rows,"gex")
    assert result["count"]==1
    assert result["median"]==-1000
    assert result["relative_disagreement"] is None
