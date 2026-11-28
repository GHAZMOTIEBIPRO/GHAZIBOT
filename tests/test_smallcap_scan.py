"""Small-cap stages: like-for-like IEX RVOL, EXTENDED never early, forward moves, encrypted record."""
import shutil

import pytest

from options_radar import smallcap_scan as sc
from scripts import run_smallcap_scan as run


def _hist(n=60, base=5.0, rng=0.2, vol=100_000):
    return [{"o": base, "h": base + rng, "l": base - rng, "c": base, "v": vol} for _ in range(n)]


def _snap(price, vol, vw=None):
    return {"latestTrade": {"p": price, "t": "2026-11-30T15:00:00Z"}, "dailyBar": {"v": vol, "vw": vw or price}}


def test_stages_from_price_volume_and_range():
    h = _hist()
    # half the session gone: expected 50k; 150k traded -> RVOL 3, price above the 20d high, +10 %
    assert sc.evaluate("AAA", _snap(5.5, 150_000), h, 0.5)["stage"] == "CONFIRMED_MOVE"
    assert sc.evaluate("BBB", _snap(5.15, 100_000), h, 0.5)["stage"] == "BREAKOUT_WATCH"  # 2 % under the high, RVOL 2
    assert sc.evaluate("CCC", _snap(5.05, 120_000), h, 0.5)["stage"] in ("EARLY_ACTIVITY", "BREAKOUT_WATCH")
    late = sc.evaluate("DDD", _snap(6.6, 400_000), h, 0.5)
    assert late["stage"] == "EXTENDED" and "EXTENDED" not in sc.ALERT_STAGES  # +32 %: never an early detection


def test_eligibility_and_honest_labels():
    h = _hist()
    assert sc.evaluate("X", _snap(25.0, 1e6), h, 0.5)["eligible"] is False
    assert sc.evaluate("Y", _snap(5.0, 10_000), h, 0.5)["reason"].startswith("IEX dollar volume")
    assert sc.evaluate("Z", _snap(5.0, 1e6), h[:10], 0.5)["eligible"] is False
    ok = sc.evaluate("AAA", _snap(5.5, 150_000), h, 0.5)
    assert ok["feed"].startswith("IEX") and ok["probability"] is None
    assert ok["levels"]["trigger"] == 5.2 and len(ok["levels"]["targets"]) == 3 and "method" in ok["levels"]


def test_forward_moves_from_first_detection():
    moves = sc.forward_moves(10.0, 30, {35: 10.5, 45: 11.0, 60: 9.0}, 12.0)
    assert moves == {"5m": 5.0, "15m": 10.0, "30m": -10.0, "60m": None, "close": 20.0}


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI needed")
def test_detection_record_is_encrypted_at_rest(tmp_path):
    path = tmp_path / "2026-11-30.json.enc"
    run.save_encrypted(path, {"AAA": {"price": 5.5, "stage": "CONFIRMED_MOVE"}}, "k3y")
    raw = path.read_bytes()
    assert b"AAA" not in raw and b"5.5" not in raw
    assert run.load_encrypted(path, "k3y") == {"AAA": {"price": 5.5, "stage": "CONFIRMED_MOVE"}}
    assert run.load_encrypted(path, "wrong") == {}


def test_universe_uses_listed_equities_and_sec_nyse(tmp_path):
    import json

    (tmp_path / "nasdaq_listed.json").write_text(json.dumps({"fields": ["symbol", "issuer", "etf", "equity"],
                                                             "rows": [["COGT", "x", 0, 1], ["QQQ", "y", 1, 0]]}))
    (tmp_path / "sec_company_tickers.json").write_text(json.dumps({"rows": [["BMY", "1", "b", "NYSE"],
                                                                             ["OTCX", "2", "o", "OTC"]]}))
    assert run.universe(tmp_path) == ["BMY", "COGT"]
