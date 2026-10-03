from options_radar.provider_readiness import assess_provider_readiness


def _audit(source, attempts, metadata=None):
    return {
        "XYZ": {
            "source": source,
            "freshness": "multi-provider exact-contract reconciliation",
            "attempts": attempts,
            "metadata": metadata or {"data_fabric": {"source_count": len(attempts)}},
        }
    }


def test_fabric_with_tradier_sandbox_and_yahoo_is_not_production():
    readiness = assess_provider_readiness(
        _audit(
            "fabric:tradier+yahoo",
            [
                {"provider": "tradier", "success": True},
                {"provider": "yahoo", "success": True},
            ],
        ),
        tradier_base_url="https://sandbox.tradier.com",
    )
    assert readiness.production_quote_ready is False
    assert readiness.production_flow_ready is False
    assert readiness.status == "FALLBACK_ONLY"


def test_fabric_production_tradier_without_verified_quote_stays_research():
    readiness = assess_provider_readiness(
        _audit(
            "fabric:tradier+yahoo",
            [
                {"provider": "tradier", "success": True},
                {"provider": "yahoo", "success": True},
            ],
        ),
        tradier_base_url="https://api.tradier.com",
    )
    assert readiness.production_quote_ready is False
    assert readiness.production_flow_ready is False
    assert readiness.status == "FALLBACK_ONLY"


def test_fabric_structured_execution_quote_is_ready_but_not_flow_ready():
    readiness = assess_provider_readiness(
        _audit(
            "fabric:tradier+yahoo",
            [
                {"provider": "tradier", "success": True},
                {"provider": "yahoo", "success": True},
            ],
            metadata={
                "data_fabric": {
                    "source_count": 2,
                    "execution_quote_checked_contracts": 4,
                    "execution_quote_ready_contracts": 1,
                    "verifiable_quote_timestamp_contracts": 1,
                }
            },
        ),
        tradier_base_url="https://api.tradier.com",
    )
    assert readiness.production_quote_ready is True
    assert readiness.production_flow_ready is False
    assert readiness.status == "LIVE_QUOTES_NO_TRADE_FLOW"


def test_fresh_opra_stream_overlay_is_production_flow_ready():
    readiness = assess_provider_readiness(
        _audit(
            "fabric:yahoo+alpaca_opra_stream",
            [{"provider": "yahoo", "success": True}],
            metadata={
                "data_fabric": {"source_count": 1},
                "stream_overlay": {
                    "execution_grade": True,
                    "execution_quotes_replaced": 4,
                    "feed": "opra",
                },
            },
        )
    )
    assert readiness.production_quote_ready is True
    assert readiness.production_flow_ready is True
    assert readiness.status == "LIVE_FLOW_READY"


def test_process_level_stream_flag_alone_never_creates_production_readiness():
    readiness = assess_provider_readiness(
        {},
        stream_active=True,
        stream_source="opra",
    )
    assert readiness.production_quote_ready is False
    assert readiness.production_flow_ready is False


def test_fake_execution_grade_non_opra_stream_is_not_live():
    readiness = assess_provider_readiness(
        _audit(
            "fabric:yahoo",
            [{"provider": "yahoo", "success": True}],
            metadata={
                "data_fabric": {"source_count": 1},
                "stream_overlay": {
                    "execution_grade": True,
                    "execution_quotes_replaced": 3,
                    "feed": "indicative",
                },
            },
        )
    )
    assert readiness.production_quote_ready is False
    assert readiness.production_flow_ready is False
