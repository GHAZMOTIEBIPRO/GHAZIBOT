from scripts.build_dynamic_options_universe import build


def test_dynamic_universe_prefers_early_candidates(tmp_path):
    fast = tmp_path / "fast.json"
    out = tmp_path / "dynamic.json"
    fast.write_text(
        '{"generated_at":"2026-09-30T19:00:00Z","candidates":['
        '{"symbol":"AAA","stage":"PRESSURE_BUILDING","score":70,"institutional_earlyness":80},'
        '{"symbol":"BBB","stage":"EXTENDED","score":99,"institutional_earlyness":10},'
        '{"symbol":"CCC","stage":"IGNITION","score":75,"institutional_earlyness":65}'
        ']}',
        encoding="utf-8",
    )
    result = build(fast, out, max_symbols=2, min_score=52)
    assert result["symbols"] == ["CCC", "AAA"]
    assert "BBB" not in result["symbols"]
    assert (tmp_path / "dynamic_options_universe.txt").read_text(encoding="utf-8").splitlines() == ["CCC", "AAA"]
