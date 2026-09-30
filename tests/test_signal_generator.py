from datetime import datetime, timedelta, timezone

from engines.signal_generator import SignalGenerator
from validators.options_validator import DataSource


class FakeValidator:
    def validate(self, **kwargs):
        class Lineage:
            def to_dict(self):
                return {"source": kwargs["source"].value}
        class Result:
            decision_authority = kwargs["source"] == DataSource.LIVE_OPRA
            rejection_reasons = [] if decision_authority else ["rejected source"]
            lineage = Lineage()
        return Result()


def quote(source="live_opra", expiration="2099-01-01"):
    return {
        "symbol": "ABC", "contract_type": "CALL", "strike": 100,
        "bid": 1.00, "ask": 1.04, "last": 1.02,
        "expiration": expiration, "source": source,
        "quote_timestamp": datetime.now(timezone.utc),
    }


def test_generates_authorized_call_with_catalysts():
    engine = SignalGenerator(FakeValidator())
    result = engine.generate(
        quote=quote(),
        bars=[{"close": 100}, {"close": 101}, {"close": 103}],
        sec_verification={"confidence_score": 1.0},
        gex=2_000_000, flow=1.0, volume_ratio=4.0,
    )
    assert result is not None
    assert result.direction == "CALL"
    assert result.decision_authority is True
    assert "سيولة غير اعتيادية" in result.catalysts
    assert "decision_authority: TRUE" in result.to_alert()


def test_rejects_yahoo_before_signal():
    engine = SignalGenerator(FakeValidator())
    result = engine.generate(
        quote=quote(source="yahoo"), bars=[{"close": 100}, {"close": 101}],
        sec_verification={"confidence_score": 1.0}, flow=1.0,
    )
    assert result is None


def test_rejects_low_sec_confidence():
    engine = SignalGenerator(FakeValidator())
    result = engine.generate(
        quote=quote(), bars=[{"close": 100}, {"close": 101}],
        sec_verification={"confidence_score": 0.84}, flow=1.0,
    )
    assert result is None


def test_horizon_classification():
    engine = SignalGenerator(FakeValidator())
    now = datetime.now(timezone.utc)
    assert engine._horizon(now.date().isoformat(), now) == "0DTE"
    assert engine._horizon((now + timedelta(days=7)).date().isoformat(), now) == "Weekly"
    assert engine._horizon((now + timedelta(days=30)).date().isoformat(), now) == "Monthly"
