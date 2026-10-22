from datetime import datetime

import exchange_calendars as xcals
import pandas as pd

from options_radar.weekly_setup_shadow import weekly_setup_shadow
from scripts.build_stock_watch_charts import pack_symbol


def bars(end='2026-10-21'):
    dates = xcals.get_calendar('XNYS').sessions_in_range('2026-06-01', end)
    idx = pd.DatetimeIndex([d.date() for d in dates]).tz_localize('America/New_York')
    rows = []
    for i, day in enumerate(idx):
        close = 20 + i * .02
        radius = .7 if day < pd.Timestamp('2026-09-28', tz=idx.tz) else .08
        rows.append([close, close + radius, close - radius, close, 1000])
    return pd.DataFrame(rows, index=idx, columns=['Open', 'High', 'Low', 'Close', 'Volume'])


def test_weekly_alignment_uses_closed_weeks_and_no_independent_authority():
    result = weekly_setup_shadow(bars(), daily_stage='TIGHT_WATCH')
    assert result['available'] is True
    assert result['status'] == 'DAILY_WEEKLY_ALIGNED'
    assert result['last_complete_week'] == '2026-10-16'
    assert result['weeks_used'] == 12
    assert result['independent_confirmation'] is False
    assert result['option_execution_eligible'] is False
    assert weekly_setup_shadow(bars(), daily_stage='NO_SETUP')['status'] == 'NO_WEEKLY_CONFIRMATION'


def test_current_week_spike_does_not_change_weekly_evidence():
    df = bars()
    expected = weekly_setup_shadow(df, daily_stage='TIGHT_WATCH')
    df.loc[df.index >= '2026-10-19', ['Open', 'High', 'Low', 'Close']] *= 10
    assert weekly_setup_shadow(df, daily_stage='TIGHT_WATCH') == expected


def test_missing_session_does_not_create_a_complete_week():
    df = bars().drop(pd.Timestamp('2026-10-13', tz='America/New_York'))
    assert weekly_setup_shadow(df, daily_stage='TIGHT_WATCH')['available'] is False
    assert weekly_setup_shadow(bars().tail(40), daily_stage='TIGHT_WATCH')['available'] is False


def test_malformed_or_duplicate_daily_bars_are_rejected():
    df = bars()
    df.loc[df.index[-10], 'High'] = float('inf')
    assert weekly_setup_shadow(df, daily_stage='TIGHT_WATCH')['available'] is False
    df = bars()
    assert weekly_setup_shadow(pd.concat([df, df.tail(1)]), daily_stage='TIGHT_WATCH')['available'] is False


def test_stock_chart_pipeline_excludes_current_day_and_week():
    df = bars('2026-10-23')
    report = pack_symbol('AAPL', df, None, None, now=datetime.fromisoformat('2026-10-23T12:00:00-04:00'))
    weekly = report['vcp_minervini_shadow']['weekly_context']
    assert weekly['available'] is True
    assert weekly['last_complete_week'] == '2026-10-16'
    assert report['options_execution_grade'] is False


def test_private_bot_message_distinguishes_weekly_context_from_independent_source():
    from scripts.alpaca_vcp_private import private_message

    message = private_message([
        {'symbol': 'AAPL', 'weekly_status': 'DAILY_WEEKLY_ALIGNED'},
        {'symbol': 'MSFT', 'weekly_status': 'NO_WEEKLY_CONFIRMATION'},
        {'symbol': 'NVDA', 'weekly_status': '<script>'},
    ], '2026-10-21')
    assert 'توافق يومي وأسبوعي من نفس المصدر' in message
    assert 'لا تأكيد أسبوعي للنموذج اليومي' in message
    assert 'الشموع الأسبوعية غير كافية' in message
    assert '<script>' not in message
