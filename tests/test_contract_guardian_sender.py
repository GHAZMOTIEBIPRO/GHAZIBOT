from types import SimpleNamespace

from scripts import send_contract_guardian_updates as sender


def _row(mark=3.0, stage="ACTIVE"):
    return {
        "contract_symbol": "XYZ261120C00100000",
        "symbol": "XYZ",
        "side": "CALL",
        "strike": 100,
        "expiration": "2026-11-20",
        "stage": stage,
        "entry_premium_reference": 2.5,
        "last_mark": mark,
        "last_return_pct": (mark / 2.5 - 1.0) * 100.0,
        "last_underlying_price": 104,
        "mfe_pct": 20,
        "mae_pct": -5,
        "quote_age_minutes": 4,
        "data_stale": False,
        "iv_crush_risk": False,
        "target_map": {
            "t1": {"price": 104},
            "t2": {"price": 108},
            "t3": {"price": 112},
            "invalidation": {"price": 96},
        },
        "premium_targets": {
            "targets": {
                "t1": {
                    "premium_low": 2.8,
                    "premium_base": 3.1,
                    "premium_high": 3.5,
                },
                "t2": {
                    "premium_low": 4.0,
                    "premium_base": 4.5,
                    "premium_high": 5.1,
                },
                "t3": {
                    "premium_low": 6.0,
                    "premium_base": 7.0,
                    "premium_high": 8.4,
                },
            }
        },
        "catalyst_health": {
            "impact_score": 88,
            "headline": "Material contract announced",
            "source": "SEC EDGAR",
        },
    }


def test_guardian_sender_creates_then_edits_same_contract_card(monkeypatch):
    calls = {"send": 0, "edit": 0}

    def fake_send(text):
        calls["send"] += 1
        assert "متابعة العقد" in text
        assert "T1" in text and "T2" in text and "T3" in text
        return SimpleNamespace(message_id=321)

    def fake_edit(message_id, text):
        calls["edit"] += 1
        assert message_id == 321
        assert "تحقق الهدف الأول" in text
        return SimpleNamespace(message_id=321, unchanged=False)

    monkeypatch.setattr(sender, "send_html_message", fake_send)
    monkeypatch.setattr(sender, "edit_html_message", fake_edit)

    state = {"contracts": {}}
    first = sender.send_updates({"active": [_row()]}, state)
    assert first == {"sent": 1, "edited": 0, "unchanged": 0}
    assert state["contracts"]["XYZ261120C00100000"]["message_id"] == 321

    second = sender.send_updates(
        {"active": [_row(mark=3.4, stage="T1_HIT")]},
        state,
    )
    assert second == {"sent": 0, "edited": 1, "unchanged": 0}
    assert calls == {"send": 1, "edit": 1}


def test_guardian_sender_dedupes_unchanged_card(monkeypatch):
    monkeypatch.setattr(
        sender,
        "send_html_message",
        lambda text: SimpleNamespace(message_id=99),
    )
    state = {"contracts": {}}
    report = {"active": [_row()]}

    sender.send_updates(report, state)

    def should_not_send(_text):
        raise AssertionError("unchanged guardian card must not send again")

    def should_not_edit(_message_id, _text):
        raise AssertionError("unchanged guardian card must not edit again")

    monkeypatch.setattr(sender, "send_html_message", should_not_send)
    monkeypatch.setattr(sender, "edit_html_message", should_not_edit)
    result = sender.send_updates(report, state)

    assert result == {"sent": 0, "edited": 0, "unchanged": 1}


def test_guardian_message_marks_stale_and_iv_crush_risk():
    row = _row()
    row["data_stale"] = True
    row["iv_crush_risk"] = True
    row["quote_age_minutes"] = 155

    message = sender._message(row)

    assert "IV Crush" in message
    assert "بيانات العقد قديمة" in message
    assert "155د" in message



def test_guardian_catalyst_uses_verified_impact_not_unverified_raw_health():
    row = _row()
    row["catalyst_health"] = {
        "impact_score": 98,
        "headline": "Unverified social rumor",
        "source": "social media",
    }
    row["explosion_thesis"] = {
        "verification": "UNVERIFIED",
        "headline": "Unverified social rumor",
        "primary_source": "social media",
        "impact_score": None,
        "proof_ar": "الخبر غير مثبت رسميًا",
    }
    card = sender._message(row)
    assert "غير مقيم — الخبر غير مثبت" in card
    assert "98/100" not in card
    assert "غير مثبت رسميًا" in card
    assert "غير مؤرخة" in card


def test_guardian_official_impact_displays_original_approved_score_only():
    row = _row()
    row["catalyst_health"] = {"impact_score": 99}
    row["explosion_thesis"] = {
        "verification": "OFFICIAL",
        "headline": "Material report filed",
        "primary_source": "SEC EDGAR",
        "impact_score": 81,
        "proof_ar": "خبر مثبت من جهة رسمية",
    }
    card = sender._message(row)
    assert "81/100" in card
    assert "99/100" not in card
    assert "SEC EDGAR" in card


def test_guardian_card_refreshes_fingerprint_when_verified_impact_changes():
    row = _row()
    row["explosion_thesis"] = {
        "verification": "OFFICIAL",
        "headline": "Report filed",
        "impact_score": 42,
    }
    first = sender._fingerprint(row)
    row["explosion_thesis"]["impact_score"] = 87
    assert sender._fingerprint(row) != first
    row["explosion_thesis"]["verification"] = "UNVERIFIED"
    assert sender._fingerprint(row) != first
