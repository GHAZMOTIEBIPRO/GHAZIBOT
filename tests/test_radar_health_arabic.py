from scripts import send_radar_health as health


def test_known_provider_health_reasons_are_translated_to_arabic():
    text = health._reason_ar("Only delayed, indicative, unofficial, or fallback option data is active")
    assert "احتياطية" in text
    assert "متأخرة" in text

    text = health._reason_ar("9 chain(s) are Yahoo/YFinance-only fallback")
    assert "9" in text
    assert "مصدر احتياطي" in text


def test_unknown_english_health_reason_does_not_leak_into_telegram():
    raw = "Unexpected upstream provider detail in English"
    translated = health._reason_ar(raw)
    assert translated != raw
    assert "سبب تقني" in translated


def test_existing_arabic_health_reason_is_preserved():
    raw = "المصدر الرسمي متأخر مؤقتًا"
    assert health._reason_ar(raw) == raw
