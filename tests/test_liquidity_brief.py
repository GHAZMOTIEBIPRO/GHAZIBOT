"""Weekly liquidity Telegram brief: one message per claims week, nothing on stale/kept/old data,
delivery only with a receipt, sources without a verified Telegram right left out."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts import send_liquidity_brief as sb

ROOT = Path(__file__).resolve().parents[1]
RIGHTS = json.loads((ROOT / "data" / "source_rights.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 10, 29, 15, 30, tzinfo=timezone.utc)


def _liq(**claims_over):
    claims = {"available": True, "stale": False, "rights": "dol_eta539", "week_ending": "2026-10-17",
              "initial_claims": 172640, "initial_claims_year_ago": 204767, "initial_claims_yoy_pct": -15.7,
              "initial_claims_4wk_avg": 173074.0, "initial_claims_4wk_avg_year_ago": 199974.0,
              "initial_claims_4wk_yoy_pct": -13.5, "band_4wk_vs_year_ago": "LOWER",
              "continued_weeks_claimed": 1472151, "continued_reflect_week": "2026-10-10", "continued_yoy_pct": -11.7,
              "source_last_modified": "Wed, 28 Oct 2026 19:50:59 GMT", **claims_over}
    return {"generated_at": "2026-10-29T15:17:00+00:00", "claims": claims,
            "funding_rates": {"available": True, "stale": False, "rights": "nyfed_reference_rates",
                              "sofr": {"date": "2026-10-27", "rate": 3.95}, "target_range": [3.75, 4.0],
                              "days_p99_above_target_top": 2, "window_days": 60,
                              "notice": {"SOFR": "The SOFR is subject to the Terms of Use posted at newyorkfed.org.",
                                         "dtcc": "DTCC Solutions LLC note."}},
            "repo": {"available": True, "rights": "ofr_stfm",
                     "tri_party_rate": {"available": True, "stale": False, "date": "2026-10-26", "value": 3.92,
                                        "change_bp": 2.0}}}


class _Sender:
    def __init__(self, receipt=101, error=None):
        self.texts, self.receipt, self.error = [], receipt, error

    def __call__(self, text):
        self.texts.append(text)
        if self.error:
            raise self.error
        return SimpleNamespace(message_id=self.receipt)


def test_sends_once_per_claims_week_with_notice_and_sources():
    send = _Sender()
    state, out = sb.run(_liq(), RIGHTS, None, now=NOW, send=send)
    assert out == {"mode": "sent", "sent": 1, "week": "2026-10-17"} and state["message_id"] == 101
    text = send.texts[0]
    assert "172,640" in text and "204,767" in text and "−15.7%" in text and "غير معدّلة موسميًا" in text
    assert "3.95%" in text and "newyorkfed.org" in text and "DTCC" in text and "3.92%" in text
    assert "وليس إشارة شراء أو بيع" in text
    for banned in ("CALL", "PUT", "تدفق", "شراء مؤسسي"):
        assert banned not in text
    # same week again: nothing sent
    state2, out2 = sb.run(_liq(), RIGHTS, state, now=NOW + timedelta(hours=8), send=send)
    assert out2["mode"] == "already_sent" and len(send.texts) == 1 and state2 == state
    # a new week is sent
    _, out3 = sb.run(_liq(week_ending="2026-10-24") | {"generated_at": "2026-11-05T15:17:00+00:00"}, RIGHTS, state,
                     now=NOW + timedelta(days=7), send=send)
    assert out3["mode"] == "sent" and len(send.texts) == 2


def test_stale_kept_or_old_data_sends_nothing():
    send = _Sender()
    assert sb.run(_liq(stale=True), RIGHTS, None, now=NOW, send=send)[1]["mode"] == "claims_not_fresh"
    kept = sb.run(_liq(kept_previous_copy=True, kept_reason="REFUSED_HTTP_403"), RIGHTS, None, now=NOW, send=send)[1]
    assert kept == {"mode": "claims_not_fresh", "sent": 0, "reason": "REFUSED_HTTP_403"}
    old = sb.run(_liq(), RIGHTS, None, now=NOW + timedelta(days=3), send=send)[1]
    assert old["mode"] == "stale_or_invalid_file"
    assert send.texts == []


def test_delivery_needs_a_receipt_and_failures_do_not_mark_the_week():
    for sender in (_Sender(receipt=None), _Sender(error=TimeoutError())):
        state, out = sb.run(_liq(), RIGHTS, None, now=NOW, send=sender)
        assert out["sent"] == 0 and "last_claims_week" not in state


def test_source_without_verified_telegram_right_is_left_out():
    rights = json.loads(json.dumps(RIGHTS))
    rights["providers"]["nyfed_reference_rates"]["rights"]["telegram_sharing"]["status"] = "UNKNOWN"
    send = _Sender()
    sb.run(_liq(), rights, None, now=NOW, send=send)
    assert "SOFR" not in send.texts[0] and "newyorkfed" not in send.texts[0] and "172,640" in send.texts[0]
    rights["providers"]["dol_eta539"]["rights"]["telegram_sharing"]["status"] = "RESTRICTED"
    assert sb.run(_liq(), rights, None, now=NOW, send=_Sender())[1]["mode"] == "claims_not_fresh"


def test_stale_sofr_is_not_shown():
    liq = _liq()
    liq["funding_rates"]["stale"] = True
    send = _Sender()
    sb.run(liq, RIGHTS, None, now=NOW, send=send)
    assert "SOFR" not in send.texts[0]
