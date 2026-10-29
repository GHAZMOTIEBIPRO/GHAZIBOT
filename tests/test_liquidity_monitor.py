"""Liquidity monitor: partial weeks fail closed, stale data is flagged, a refused or broken source keeps
its last good copy with the reason, and the New York Fed notice travels with the rates."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lm = _load("ghazi_liquidity_monitor_t", "options_radar/liquidity_monitor.py")
builder = _load("ghazi_build_liquidity_t", "scripts/build_liquidity_monitor.py")
HF = builder.hf

HEADER = '"st","rptdate","c1","c2","c3","c4","c5","c6","c7","c8"'


def _csv(weeks: list[date], states=("AK", "AL", "CA"), ic=100, cw=1000, skip: dict | None = None) -> str:
    lines = [HEADER]
    for w in weeks:
        for st in states:
            if skip and st in skip.get(w, ()):
                continue
            lines.append(f'"{st}","{w}",1,{w - timedelta(days=7)},{ic},0,0,0,0,{cw}')
    return "\n".join(lines) + "\n"


def _weeks(end: date, n: int) -> list[date]:
    return [end - timedelta(days=7 * i) for i in range(n)][::-1]


def test_partial_latest_week_is_not_summed_and_year_ago_comparison_uses_same_week():
    end = date(2026, 10, 24)
    weeks = _weeks(end, 60)
    text = _csv(weeks, skip={end: ("CA",)})  # latest week: one state not yet reported
    rows, rejected = lm.parse_ar539(text)
    c = lm.claims(rows, today=date(2026, 10, 29), source_last_modified="Wed, 28 Oct 2026 19:50:59 GMT")
    assert rejected == 0 and c["available"]
    assert c["week_ending"] == "2026-10-17"  # the last complete week
    assert c["incomplete_weeks"] == [{"week_ending": "2026-10-24", "states": 2, "expected": 3}]
    assert c["initial_claims"] == 300 and c["initial_claims_year_ago"] == 300 and c["initial_claims_yoy_pct"] == 0.0
    assert c["seasonally_adjusted"] is False and c["source_last_modified"].startswith("Wed")


def test_chart_pairs_each_week_with_the_same_week_a_year_earlier_and_band_rule():
    end = date(2026, 10, 17)
    weeks = _weeks(end, 110)
    lines = [HEADER]
    for i, w in enumerate(weeks):  # the last 40 weeks run 10% above the same weeks a year before
        ic = 110 if i >= 70 else 100
        lines += [f'"{st}","{w}",1,{w - timedelta(days=7)},{ic},0,0,0,0,1000' for st in ("AK", "AL")]
    rows, _ = lm.parse_ar539("\n".join(lines) + "\n")
    c = lm.claims(rows, today=end + timedelta(days=11), source_last_modified=None)
    assert len(c["chart_52w"]) == 52 and c["chart_52w"][-1] == ["2026-10-17", 220, 200]
    assert c["initial_claims_4wk_yoy_pct"] == 10.0 and c["band_4wk_vs_year_ago"] == "HIGHER"
    assert "±5%" in c["band_rule"]
    # a year-ago week missing from the file stays None in the chart
    short, _ = lm.parse_ar539(_csv(_weeks(end, 10)))
    assert lm.claims(short, today=end, source_last_modified=None)["chart_52w"][-1][2] is None


def test_sofr_history_counts_days_with_the_99th_percentile_above_the_range_top():
    sofr = lm.reference_rates({"refRates": [
        {"effectiveDate": "2026-10-26", "percentRate": 3.93, "percentPercentile99": 4.01},
        {"effectiveDate": "2026-10-27", "percentRate": 3.95, "percentPercentile99": 3.99}]})
    effr = lm.reference_rates({"refRates": [
        {"effectiveDate": d, "percentRate": 3.88, "targetRateFrom": 3.75, "targetRateTo": 4.0}
        for d in ("2026-10-26", "2026-10-27")]})
    f = lm.funding_rates(sofr, effr, today=date(2026, 10, 29))
    assert f["sofr_history"][-1] == ["2026-10-27", 3.95, 3.99, 4.0]
    assert f["window_days"] == 2 and f["days_p99_above_target_top"] == 1


def test_duplicate_and_malformed_rows():
    end = date(2026, 10, 17)
    text = _csv(_weeks(end, 3)) + f'"AK","{end}",1,{end},100,0,0,0,0,1000\n"ZZ","not-a-date",1,,5\n'
    rows, rejected = lm.parse_ar539(text)
    c = lm.claims(rows, today=end + timedelta(days=11), source_last_modified=None)
    assert rejected == 1
    assert c["initial_claims"] == 300  # the repeated AK row is not added twice
    assert c["initial_claims_year_ago"] is None and c["initial_claims_yoy_pct"] is None  # no history: missing, not 0


def test_stale_claims_are_flagged():
    end = date(2026, 9, 5)
    rows, _ = lm.parse_ar539(_csv(_weeks(end, 5)))
    c = lm.claims(rows, today=date(2026, 10, 29), source_last_modified=None)
    assert c["stale"] is True and c["age_days"] == 54


def _rates(name: str, d: str, rate: float, **extra) -> dict:
    return {"refRates": [{"effectiveDate": d, "type": name, "percentRate": rate, "percentPercentile99": rate + 0.09,
                          "volumeInBillions": 3000, "revisionIndicator": "", **extra}]}


def test_funding_rates_carry_the_required_notice_and_same_day_target():
    sofr = lm.reference_rates(_rates("SOFR", "2026-10-27", 3.95))
    effr = lm.reference_rates(_rates("EFFR", "2026-10-27", 3.88, targetRateFrom=3.75, targetRateTo=4.0))
    f = lm.funding_rates(sofr, effr, today=date(2026, 10, 29))
    assert f["target_range"] == [3.75, 4.0] and f["sofr_minus_target_top_bp"] == -5.0
    assert f["sofr_minus_effr_bp"] == 7.0
    assert "subject to the Terms of Use posted at newyorkfed.org" in f["notice"]["SOFR"]
    assert "DTCC Solutions LLC" in f["notice"]["dtcc"]
    assert lm.funding_rates([], effr, today=date(2026, 10, 29)) == {"available": False, "reason": "SOFR_MISSING"}


class _Fetcher:
    """Answers by URL fragment; records the conditional header sent for the DOL file."""

    def __init__(self, answers: dict[str, object]):
        self.answers, self.calls = answers, []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        for fragment, answer in self.answers.items():
            if fragment in url:
                if isinstance(answer, str):
                    return HF.FetchResult(url=url, outcome=answer, http={"REFUSED": 403, "NOT_MODIFIED": 304}.get(answer))
                return answer(url)
        return HF.FetchResult(url=url, outcome="NETWORK_ERROR", error="URLError")


def _ok(body, last_modified=None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    return lambda url: HF.FetchResult(url=url, outcome="OK", http=200, body=data, last_modified=last_modified)


NOW = datetime(2026, 10, 29, 15, 17, tzinfo=timezone.utc)
SERIES = [["2026-09-25", 3.9], ["2026-10-26", 3.92]]
META = {"description": {"vintage": "Preliminary"}, "schedule": {"last_update": "2026-10-28 14:17:04"},
        "unit": {"name": "Percent"}}


def _all_ok():
    return {"ar539": _ok(_csv(_weeks(date(2026, 10, 17), 60)).encode(), "Wed, 28 Oct 2026 19:50:59 GMT"),
            "sofr": _ok(_rates("SOFR", "2026-10-27", 3.95)),
            "effr": _ok(_rates("EFFR", "2026-10-27", 3.88, targetRateFrom=3.75, targetRateTo=4.0)),
            "series/timeseries": _ok(SERIES), "metadata/query": _ok(META)}


def test_builder_end_to_end_and_last_good_copy_on_refusal(tmp_path):
    out = tmp_path / "liquidity_monitor.json"
    assert builder.main(["--output", str(out)], fetcher=_Fetcher(_all_ok()), now=NOW) == 0
    first = json.loads(out.read_text(encoding="utf-8"))
    assert first["claims"]["initial_claims"] == 300 and first["funding_rates"]["sofr"]["rate"] == 3.95
    assert first["repo"]["tri_party_rate"]["change_bp"] == 2.0 and first["is_signal"] is False
    assert first["funding_rates"]["rights"] == "nyfed_reference_rates"

    # second run: DOL refuses, New York Fed unreachable, OFR fine
    answers = _all_ok() | {"ar539": "REFUSED", "sofr": "NETWORK_ERROR", "effr": "NETWORK_ERROR"}
    fetcher = _Fetcher(answers)
    assert builder.main(["--output", str(out)], fetcher=fetcher, now=NOW + timedelta(days=1)) == 0
    second = json.loads(out.read_text(encoding="utf-8"))
    assert second["claims"]["kept_previous_copy"] is True and second["claims"]["kept_reason"] == "REFUSED_HTTP_403"
    assert second["claims"]["initial_claims"] == 300  # the published value as of its own week, labelled
    assert second["funding_rates"]["kept_previous_copy"] is True
    assert "NETWORK_ERROR" in second["funding_rates"]["kept_reason"]
    assert "kept_previous_copy" not in second["repo"]
    # incremental: the previous Last-Modified was sent
    dol_call = next(kw for url, kw in fetcher.calls if "ar539" in url)
    assert dol_call["if_modified_since"] == "Wed, 28 Oct 2026 19:50:59 GMT"


def test_not_modified_keeps_values_without_marking_them_as_a_kept_copy(tmp_path):
    out = tmp_path / "liquidity_monitor.json"
    builder.main(["--output", str(out)], fetcher=_Fetcher(_all_ok()), now=NOW)
    builder.main(["--output", str(out)], fetcher=_Fetcher(_all_ok() | {"ar539": "NOT_MODIFIED"}),
                 now=NOW + timedelta(days=30))
    c = json.loads(out.read_text(encoding="utf-8"))["claims"]
    assert c["initial_claims"] == 300 and "kept_previous_copy" not in c
    assert c["age_days"] == 42 and c["stale"] is True  # unchanged file, ageing data: still flagged


def test_nothing_validated_and_no_previous_file_writes_nothing(tmp_path):
    out = tmp_path / "liquidity_monitor.json"
    assert builder.main(["--output", str(out)], fetcher=_Fetcher({}), now=NOW) == 1
    assert not out.exists()
