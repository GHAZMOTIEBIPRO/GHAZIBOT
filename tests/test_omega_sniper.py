from scripts.omega_sniper import format_omega_sniper_message
from scripts.sniper_signal import parse_sniper_event


def test_omega_message_contains_arabic_execution_fields():
    event = parse_sniper_event(
        {
            "schema": "sniper.v2",
            "source": "sniper",
            "symbol": "SPX",
            "direction": "CALL",
            "score": 91,
            "grade": "A",
            "horizon": "يومي",
            "timeframe": "5m",
            "entry": 6855,
            "trigger": 6863,
            "stop": 6847,
            "target_1": 6875,
            "target_2": 6892,
        },
        now=None,
    )
    message = format_omega_sniper_message(event)
    assert event.symbol == "SPX"
    assert "منطقة الدخول" in message
    assert "الهدف الأول" in message
    assert "الهدف الثاني" in message
    assert "نافذة الهدف الأول" in message
    assert len(message) <= 4096
