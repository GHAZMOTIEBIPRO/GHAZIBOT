import json
from datetime import datetime, timezone

from scripts.build_data_hub import REGISTRY, assess, build

TUE_OPEN = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
TUE_NIGHT = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
ENTRY = next(e for e in REGISTRY if e["file"] == "liquidity_map.json")  # cadence 60


def test_freshness_uses_dataset_timestamp_and_cadence():
    fresh = assess(ENTRY, {"generated_at": "2026-10-20T13:00:00+00:00"}, TUE_OPEN)
    assert fresh["freshness"] == "FRESH" and fresh["age_minutes"] == 120.0
    stale = assess(ENTRY, {"generated_at": "2026-10-20T10:00:00+00:00"}, TUE_OPEN)
    assert stale["freshness"] == "STALE"  # 300 min > 3 x 60 during the session
    overnight = assess(ENTRY, {"generated_at": "2026-10-19T20:00:00+00:00"}, TUE_NIGHT)
    assert overnight["freshness"] == "FRESH"  # 7h overnight is within the 18h tolerance


def test_missing_untimed_future_and_guard_failures():
    assert assess(ENTRY, None, TUE_OPEN)["freshness"] == "MISSING"
    assert assess(ENTRY, {"x": 1}, TUE_OPEN)["freshness"] == "UNTIMED"
    assert assess(ENTRY, {"generated_at": "2026-10-20T16:00:00+00:00"}, TUE_OPEN)["freshness"] == "FUTURE_TIMESTAMP"
    bad = assess(ENTRY, {"generated_at": "2026-10-20T14:00:00+00:00", "execution_grade": True}, TUE_OPEN)
    assert bad["validation"] == "FAIL" and bad["validation_problems"] == ["execution_grade!=False"]


def test_build_catalogs_every_registered_file(tmp_path):
    (tmp_path / "liquidity_map.json").write_text(json.dumps({"generated_at": "2026-10-20T14:30:00+00:00"}))
    (tmp_path / "index_radar.json").write_text("{not json")
    report = build(tmp_path, TUE_OPEN)
    rows = {r["file"]: r for r in report["datasets"]}
    assert len(rows) == len(REGISTRY)
    assert rows["liquidity_map.json"]["freshness"] == "FRESH"
    assert rows["index_radar.json"]["validation"] == "FAIL"
    assert rows["options_analytics.json"]["freshness"] == "MISSING"
    assert report["summary"]["fallback_sources"] == []
    assert rows["stock_watch_charts.json"]["license_class"] == "TERMS_RESTRICTED"
    assert set(report["source_gates"]) == {"cboe_delayed", "yahoo", "nasdaq_web", "community_gex",
                                           "occ_market_data", "nasdaqtrader", "finra_api", "fred", "bls",
                                           "google_news", "press_wire_rss"}
    assert report["policy"]["network_requests"] is False


def test_every_dataset_gets_one_directive_state(tmp_path):
    stamp = {"generated_at": "2026-10-20T14:30:00+00:00"}
    for name, extra in {"liquidity_map.json": {}, "public_macro.json": {}, "fda_events.json": {},
                        "stock_audit_public.json": {}, "site_smoke.json": {},
                        "decision_brief.json": {"execution_grade": True},
                        "site_strength.json": {"generated_at": "2026-10-10T00:00:00+00:00"},
                        "free_public_intelligence.json": {"status": "SOURCE_UNAVAILABLE"}}.items():
        (tmp_path / name).write_text(json.dumps({**stamp, **extra}))
    report = build(tmp_path, TUE_OPEN)
    states = {r["file"]: r["data_state"] for r in report["datasets"]}
    assert states["liquidity_map.json"] == "LICENSE_BLOCKED"  # Yahoo-derived: rights beat freshness
    assert states["public_macro.json"] == "DELAYED" and states["fda_events.json"] == "DELAYED"
    assert states["stock_audit_public.json"] == "HISTORICAL"
    assert states["site_smoke.json"] == "RESEARCH_ONLY"
    assert states["decision_brief.json"] == "VALIDATION_FAILED"
    assert states["site_strength.json"] == "STALE"
    assert states["free_public_intelligence.json"] == "SOURCE_UNAVAILABLE"
    assert states["options_analytics.json"] == "DATA_UNAVAILABLE"
    assert "LIVE" not in states.values()
    assert sum(report["summary"]["data_states"].values()) == len(REGISTRY)
    assert all(r["data_state_ar"] == report["data_states"][r["data_state"]] for r in report["datasets"])


def test_engines_split_providers_by_recorded_rights_only():
    from scripts.build_data_hub import _source_rights, provider_class

    engines = _source_rights()["engines"]
    assert set(engines) == {"PRICE", "VOLUME", "NEWS", "FUNDAMENTAL", "OPTIONS", "MACRO", "REGULATORY"}
    # No free price provider is publishable; Twelve Data is internal research only.
    assert engines["PRICE"]["public_sources"] == [] and engines["VOLUME"]["public_sources"] == []
    assert "twelve_data" in engines["PRICE"]["internal_only_sources"]
    assert engines["PRICE"]["providers"]["tradingview_widgets"] == "DISPLAY_WIDGET_ONLY"
    assert engines["PRICE"]["providers"]["yahoo"] == "BLOCKED"
    assert engines["OPTIONS"]["status"] == "NO_PERMITTED_SOURCE"
    assert engines["MACRO"]["status"] == "PUBLIC_SOURCE_AVAILABLE"
    assert "openfda" in engines["REGULATORY"]["public_sources"]
    assert "gdelt" in engines["NEWS"]["public_sources"] and engines["NEWS"]["providers"]["google_news_rss"] == "BLOCKED"
    assert provider_class("x", {"automated_access": "UNKNOWN"}) == "UNKNOWN"
