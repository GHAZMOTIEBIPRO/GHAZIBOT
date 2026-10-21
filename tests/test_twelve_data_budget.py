"""Twelve Data credit plan, quota guard and in-memory cache (fixture payloads, no network)."""
import pytest

from options_radar import twelve_data_budget as td


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def test_engine_plan_fits_the_free_plan_with_headroom():
    report = td.plan_report(td.FREE_PLAN)
    assert report["fits"] is True and report["headroom_credits"] >= 0
    assert report["planned_credits_per_day"] == sum(b.credits_per_day for b in td.ENGINE_PLAN.values())
    assert report["allowed_credits_per_day"] == int(td.FREE_PLAN["credits_per_day"] * td.DAILY_HEADROOM)
    # One run never needs more than a few minutes at the per-minute limit.
    assert max(e["minutes_per_run_at_limit"] for e in report["engines"].values()) <= 8


def test_plan_report_flags_a_plan_that_does_not_fit():
    big = {"x": td.EngineBudget(symbols=100, interval="5min", runs_per_day=78)}
    assert td.plan_report(td.FREE_PLAN, big)["fits"] is False


def test_limits_from_environment_only_when_positive_integers():
    assert td.plan_limits({"TWELVE_DATA_CREDITS_PER_MINUTE": "55", "TWELVE_DATA_CREDITS_PER_DAY": "x"}) == {
        "credits_per_minute": 55, "credits_per_day": td.FREE_PLAN["credits_per_day"]}
    assert td.plan_limits({"TWELVE_DATA_CREDITS_PER_MINUTE": "0"}) == td.FREE_PLAN


def test_guard_waits_for_the_minute_window_then_stops_at_the_run_allowance():
    clock = Clock()
    guard = td.CreditGuard(per_minute=8, per_run=12, clock=clock, sleep=clock.sleep)
    guard.acquire(8)
    guard.acquire(4)                      # waits for the window instead of exceeding 8/min
    assert clock.t >= 1060 and guard.used == 12
    with pytest.raises(td.QuotaExhausted, match="run allowance"):
        guard.acquire(1)


def test_guard_refuses_waits_longer_than_allowed_and_oversized_requests():
    clock = Clock()
    guard = td.CreditGuard(per_minute=8, per_run=100, max_wait_seconds=5, clock=clock, sleep=clock.sleep)
    guard.acquire(8)
    with pytest.raises(td.QuotaExhausted, match="wait limit"):
        guard.acquire(1)
    with pytest.raises(td.QuotaExhausted, match="per minute"):
        td.CreditGuard(per_minute=8, per_run=100).acquire(9)


def test_cache_dedupes_within_one_interval_and_credit_errors_raise():
    clock = Clock()
    guard = td.CreditGuard(per_minute=8, per_run=100, clock=clock, sleep=clock.sleep)
    cache = td.RequestCache(clock=clock)
    calls = []
    payload = {"status": "ok", "values": [{"datetime": "2026-10-20", "close": "1"}]}

    def fetch():
        calls.append(1)
        return payload

    kwargs = {"key": ("time_series", "SPY", "15min"), "interval": "15min", "symbols": 1, "endpoint": "time_series",
              "guard": guard, "cache": cache}
    assert td.guarded_fetch(fetch, **kwargs) is payload
    assert td.guarded_fetch(fetch, **kwargs) is payload
    assert len(calls) == 1 and guard.used == 1
    clock.t += 900
    td.guarded_fetch(fetch, **kwargs)
    assert len(calls) == 2
    exhausted = {"status": "error", "code": 429,
                 "message": "You have run out of API credits for the current minute."}
    with pytest.raises(td.QuotaExhausted):
        td.guarded_fetch(lambda: exhausted, **{**kwargs, "key": ("time_series", "QQQ", "15min")})
    assert td.is_credit_error({"status": "error", "code": 400, "message": "symbol not found"}) is False


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_adapter_uses_the_guard_cache_and_reports_exhaustion(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from options_radar import market_bars as mb

    calls = []
    replies = [FakeResponse(200, {"status": "ok", "values": [
        {"datetime": "2026-10-20", "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "10"}]}),
        FakeResponse(429, {})]

    def fake_get(url, params, timeout):
        calls.append(params["symbol"])
        return replies[len(calls) - 1]

    monkeypatch.setattr(mb.requests, "get", fake_get)
    monkeypatch.setattr(mb, "_TD_GUARD", td.CreditGuard(per_minute=8, per_run=8))
    monkeypatch.setattr(mb, "_TD_CACHE", td.RequestCache())
    settings = SimpleNamespace(twelve_data_api_key="fixture-key")
    start, end = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 10, 21, tzinfo=timezone.utc)
    first = mb._twelve_data(settings, "SPY", interval="1d", start=start, end=end)
    again = mb._twelve_data(settings, "SPY", interval="1d", start=start, end=end)
    assert len(first.frame) == 1 and len(again.frame) == 1 and calls == ["SPY"]
    with pytest.raises(td.QuotaExhausted):
        mb._twelve_data(settings, "QQQ", interval="1d", start=start, end=end)
    assert mb._TD_GUARD.used == 2


def test_nothing_is_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    clock = Clock()
    td.guarded_fetch(lambda: {"status": "ok"}, key=("quote", "SPY", "1day"), interval="1day", symbols=1,
                     endpoint="quote", guard=td.CreditGuard(per_minute=8, per_run=8, clock=clock, sleep=clock.sleep),
                     cache=td.RequestCache(clock=clock))
    assert list(tmp_path.iterdir()) == []
