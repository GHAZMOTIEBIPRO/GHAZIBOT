from options_radar import free_data_health as health


def test_free_data_health_groups_same_family_without_quorum_inflation(monkeypatch):
    sources = (
        {
            "name": "SEC one",
            "url": "https://example.test/sec1",
            "family": "sec_edgar",
            "authority": "official",
            "role": "one",
            "method": "GET",
        },
        {
            "name": "SEC two",
            "url": "https://example.test/sec2",
            "family": "sec_edgar",
            "authority": "official",
            "role": "two",
            "method": "GET",
        },
        {
            "name": "Shadow",
            "url": "https://example.test/shadow",
            "family": "github_gamma_research",
            "authority": "open_source_shadow",
            "role": "shadow",
            "method": "GET",
        },
    )
    monkeypatch.setattr(health, "SOURCES", sources)
    monkeypatch.setattr(
        health,
        "_request",
        lambda source, timeout=10: {
            "ok": source["name"] != "SEC two",
            "status": 200 if source["name"] != "SEC two" else 503,
            "bytes_sampled": 100,
            "content_type": "application/json",
        },
    )

    payload = health.build_health_payload()

    assert payload["version"] == "FREE_DATA_FABRIC_V2"
    assert payload["overall"] == "partial"
    assert payload["official_sources_ok"] == 1
    assert payload["official_sources_total"] == 2
    assert payload["families"]["sec_edgar"]["sources"] == 2
    assert payload["families"]["sec_edgar"]["ok_sources"] == 1
    assert payload["policy"]["same_family_does_not_increase_source_quorum"] is True
    assert all(row["signal_authority"] is False for row in payload["sources"])


def test_shadow_success_cannot_hide_total_official_outage(monkeypatch):
    sources = (
        {
            "name": "Official",
            "url": "https://example.test/official",
            "family": "official_family",
            "authority": "official",
            "role": "official",
            "method": "GET",
        },
        {
            "name": "Shadow",
            "url": "https://example.test/shadow",
            "family": "shadow_family",
            "authority": "open_source_shadow",
            "role": "shadow",
            "method": "GET",
        },
    )
    monkeypatch.setattr(health, "SOURCES", sources)

    def fake_request(source, timeout=10):
        if source["authority"] == "official":
            raise RuntimeError("official down")
        return {
            "ok": True,
            "status": 200,
            "bytes_sampled": 10,
            "content_type": "text/plain",
        }

    monkeypatch.setattr(health, "_request", fake_request)
    payload = health.build_health_payload()

    assert payload["overall"] == "degraded"
    assert payload["official_sources_ok"] == 0
    assert payload["shadow_sources_ok"] == 1
    assert payload["policy"]["official_outage_does_not_promote_shadow_source"] is True
