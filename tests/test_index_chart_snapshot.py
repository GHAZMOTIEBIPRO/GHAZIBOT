"""Chart data remains from last completed provider candle, never fake intraday."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scripts.build_index_chart_snapshot import chart_report, pack_bars

NY=ZoneInfo("America/New_York")
NOW=datetime(2026,10,16,15,46,tzinfo=NY)


def history():
    dates=pd.bdate_range(end="2026-10-16",periods=90,tz=NY)
    points=[400+i*.5 for i in range(len(dates))]
    return pd.DataFrame({"Open":points,"High":[v+1.1 for v in points],
      "Low":[v-1.1 for v in points],"Close":points,
      "Volume":[100]*len(dates)},index=dates)


def quarter():
    times=pd.date_range("2026-10-16 09:30",periods=28,freq="15min",tz=NY)
    values=[450+i*.07 for i in range(len(times))]
    return pd.DataFrame({"Open":values,"High":[v+.2 for v in values],
      "Low":[v-.2 for v in values],"Close":values,
      "Volume":[250]*len(times)},index=times)


def minute():
    times=pd.date_range("2026-10-16 09:30",periods=80,freq="5min",tz=NY)
    values=[450+i*.04 for i in range(len(times))]
    return pd.DataFrame({"Open":values,"High":[v+.25 for v in values],
      "Low":[v-.25 for v in values],"Close":values,
      "Volume":[250]*len(times)},index=times)


def test_no_incomplete_daily_or_intraday_bar_repaint():
    data=chart_report({"SPX":history()},{"SPX":quarter()},{"SPX":minute()},now=NOW)
    assert data["schema"]=="ghazi.index_charts.v1"
    assert data["quote_execution_eligible"] is False
    assert data["data_role"]=="RESEARCH_ONLY_NOT_LICENSED_EXECUTION"
    spx=data["symbols"]["SPX"]["intervals"]
    assert spx["1d"]["bars"][-1]["time"]=="2026-10-15"
    assert spx["15m"]["bars"][-1]["time"]==int(
        pd.Timestamp("2026-10-16 15:30",tz=NY).timestamp())
    assert spx["5m"]["bars"][-1]["time"]==int(
        pd.Timestamp("2026-10-16 15:40",tz=NY).timestamp())
    assert spx["5m"]["technical"]["ema_fast"] is not None
    assert spx["5m"]["current_session_confirmed"] is True
    assert spx["1d"]["research_only"] is True


def test_weekend_bars_never_called_current():
    weekend=datetime(2026,10,18,12,tzinfo=NY)
    data=chart_report({"NDX":history()},{"NDX":quarter()},{"NDX":minute()},
                      now=weekend)
    assert data["symbols"]["NDX"]["intervals"]["15m"]["current_session_confirmed"] is False
    assert data["symbols"]["NDX"]["intervals"]["5m"]["current_session_confirmed"] is False
    assert data["symbols"]["NDX"]["intervals"]["1d"]["bars"][-1]["time"]=="2026-10-16"


def test_broken_ohlc_and_untrusted_intraday_times_rejected():
    daily=history()
    daily.iloc[0,daily.columns.get_loc("High")]=1.0
    assert len(pack_bars(daily,interval="1d"))==89
    intraday=minute()
    intraday.index=intraday.index.tz_localize(None)
    report=chart_report({"SPX":history()},{"SPX":intraday},{},now=NOW)
    assert "15m" not in report["symbols"]["SPX"]["intervals"]
    with pytest.raises(ValueError):
        chart_report({}, {}, {}, now=NOW)


def test_chart_source_is_same_index_fetch_cycle_without_second_scheduler():
    runner=Path("scripts/build_index_context.py").read_text(encoding="utf-8")
    task=Path(".github/workflows/index-radar.yml").read_text(encoding="utf-8")
    assert "--charts-output" in runner
    assert "charts = chart_report(daily, intraday, five_min, now=now)" in runner
    assert "index_charts.json" in task
    assert "PYTHONPATH=app" in task
    assert "runtime/public/data/index_radar.json runtime/public/data/index_charts.json" in task


def test_frontend_sections_preserve_old_beta_and_chart_library():
    html=Path("public/index.html").read_text(encoding="utf-8")
    for name in ("indices","large","small","news","chart","advanced"):
        assert f'id="terminal-panel-{name}"' in html
        assert f'data-terminal-tab="{name}"' in html
    assert 'id="legacy-dashboard" hidden' in html
    assert 'id="tab-options"' in html
    assert 'id="tab-chart"' in html
    assert "terminal-hub.css" in html
    assert "terminal-hub.js" in html
    assert "lightweight-charts@5.2.1" in html
