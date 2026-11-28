"""Put-call parity forward: correct level, quality gates, never labelled as the cash index."""
from datetime import date, datetime, timedelta, timezone

from options_radar import parity_reference as pr

T0 = datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc)
EXP = date(2026, 11, 30)


def _occ(root, k, cp):
    return f"{root}261130{cp}{int(k * 1000):08d}"


def _chain(forward=6012.0, root="SPXW", spread=0.4, age=0, skip_puts=()):
    snaps = {}
    for k in range(5950, 6080, 5):
        intrinsic_c, intrinsic_p = max(forward - k, 0), max(k - forward, 0)
        extrinsic = 8.0 * pow(2.718, -abs(k - forward) / 40)
        for cp, mid in (("C", intrinsic_c + extrinsic), ("P", intrinsic_p + extrinsic)):
            if cp == "P" and k in skip_puts:
                continue
            stamp = (T0 - timedelta(seconds=age)).isoformat()
            snaps[_occ(root, k, cp)] = {"latestQuote": {"bp": mid - spread / 2, "ap": mid + spread / 2, "t": stamp}}
    return snaps


def test_parity_recovers_the_forward_and_is_never_the_cash_index():
    out = pr.implied_forward(_chain(), root="SPXW", expiry=EXP, years_to_expiry=1 / 365 / 24)
    assert out["status"] == "OK" and abs(out["forward"] - 6012.0) < 0.05
    assert out["is_cash_index"] is False and out["type"] == "IMPLIED_FORWARD_FROM_PUT_CALL_PARITY"
    assert out["strikes_used"] == pr.NEAREST and out["dispersion_bp"] < 1
    assert "forward" not in pr.public_metrics(out) and pr.public_metrics(out)["status"] == "OK"


def test_quality_gates_fail_closed():
    other_root = pr.implied_forward(_chain(root="SPX"), root="SPXW", expiry=EXP, years_to_expiry=0.001)
    assert other_root["status"] == "NO_PAIRED_QUOTES"
    wide = pr.implied_forward(_chain(spread=20.0), root="SPXW", expiry=EXP, years_to_expiry=0.001)
    assert wide["status"] in ("TOO_FEW_VALID_STRIKES", "NO_PAIRED_QUOTES") and "forward" not in wide
    stale = _chain()
    for sym in list(stale)[: len(stale) // 2]:
        stale[sym]["latestQuote"]["t"] = (T0 - timedelta(minutes=30)).isoformat()
    out = pr.implied_forward(stale, root="SPXW", expiry=EXP, years_to_expiry=0.001)
    assert out["status"] in ("OK", "LOW_QUALITY") and out["max_quote_age_s"] <= pr.MAX_AGE_S


def test_crossed_or_zero_bid_quotes_are_ignored_and_occ_parsing():
    chain = _chain()
    chain[_occ("SPXW", 6010, "C")]["latestQuote"].update(bp=9.0, ap=8.0)  # crossed
    assert pr._quote(chain[_occ("SPXW", 6010, "C")]) is None
    assert pr.parse_occ("SPXW261130C06010000") == {"root": "SPXW", "expiry": EXP, "type": "C", "strike": 6010.0}
    assert pr.parse_occ("bad") is None
