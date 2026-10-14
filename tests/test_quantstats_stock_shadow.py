from types import SimpleNamespace

from scripts.run_quantstats_stock_shadow import build_quantstats_research


def _event(i, *, pct=None, status=None, covered=True):
    return {
        "signal_id": str(i),
        "symbol": "MU" if i % 2 else "AAPL",
        "signal_time": f"2026-10-{i // 2 + 1:02d}T14:00:00+00:00",
        "signal_session_date": f"2026-10-{i // 2 + 1:02d}",
        "signal_session_valid": True,
        "coverage": {"60m": covered},
        "audit_status": status or ("success" if i % 2 else "failed"),
        "entry_score": 80,
        "checkpoints": {
            "60m": {
                "coverage_qualified": covered,
                "directional_return_pct": pct if pct is not None else (2 if i % 2 else -1),
            },
        },
    }


def _audit(count=24, *, coverage=95):
    return {
        "coverage": {"coverage_60m_pct": coverage},
        "records": {str(i): _event(i) for i in range(count)},
    }


class _ReferenceQuantStats:
    @staticmethod
    def win_rate(series):
        assert len(series) == 24
        assert float(series.max()) == 0.02
        return 0.5

    @staticmethod
    def profit_factor(series):
        positive = float(series[series > 0].sum())
        negative = -float(series[series < 0].sum())
        return positive / negative


def test_quantstats_event_scope_does_not_claim_portfolio_performance():
    qs = SimpleNamespace(stats=_ReferenceQuantStats())
    result = build_quantstats_research(_audit(), quantstats_module=qs)
    assert result["status"] == "RESEARCH_METRICS_ONLY"
    assert result["counts"]["eligible_decisive_observations"] == 24
    assert result["counts"]["distinct_sessions"] == 12
    assert result["metrics"]["event_win_rate"] == 0.5
    assert result["metrics"]["event_profit_factor"] == 2.0
    assert result["realized_portfolio_pnl"] is False
    assert result["annualized_metrics_allowed"] is False
    assert result["live_alert_weights_changed"] is False


def test_insufficient_sessions_and_low_coverage_fail_closed():
    qs = SimpleNamespace(stats=_ReferenceQuantStats())
    result = build_quantstats_research(_audit(count=12), quantstats_module=qs)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    result = build_quantstats_research(_audit(coverage=55), quantstats_module=qs)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["metrics"] == {}


def test_no_partial_unqualified_or_invalid_session_records_in_metrics():
    audit = _audit()
    audit["records"]["0"]["signal_session_valid"] = False
    audit["records"]["1"]["coverage"]["60m"] = False
    audit["records"]["1"]["checkpoints"]["60m"]["coverage_qualified"] = False
    result = build_quantstats_research(
        audit, minimum_records=24,
        quantstats_module=SimpleNamespace(stats=_ReferenceQuantStats()),
    )
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["counts"]["eligible_decisive_observations"] == 22


def test_missing_or_undefined_event_metrics_never_claim_accuracy():
    data = _audit()
    for row in data["records"].values():
        row["checkpoints"]["60m"]["directional_return_pct"] = None
    assert build_quantstats_research(data)["status"] == "INSUFFICIENT_EVIDENCE"


def test_malformed_audit_returns_insufficient_evidence():
    output = build_quantstats_research({})
    assert output["status"] == "INSUFFICIENT_EVIDENCE"
    assert output["decision_authority"] is False


def test_quantstats_missing_dependency_does_not_modify_the_market_gate(monkeypatch):
    import builtins

    real = builtins.__import__

    def no_quantstats(name, *args, **kwargs):
        if name == "quantstats":
            raise ImportError("optional module not present")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_quantstats)
    report = build_quantstats_research(_audit())
    assert report["status"] == "UNAVAILABLE"
    assert report["metrics"] == {}
    assert report["execution_grade"] is False
