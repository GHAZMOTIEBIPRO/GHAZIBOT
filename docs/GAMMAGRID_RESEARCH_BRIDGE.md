# External options dashboards — phased integration

## What this patch actually integrates

This is a **read-only, optional, operator-provided normalized GammaGrid research snapshot** consumed by the existing `build_spx_external_context()`. This is **not** a live GammaGrid MCP session, a browser scraping client, or an automatic export facility. No credentials, arbitrary remote URLs, AGPL source code, or new network calls are introduced.

GammaGrid's self-hosted application uses Yahoo options-chain data and has an AGPL-3.0 license. Its hosted MCP connector requires a separate authorized OAuth session, and no supported unattended export/API contract was established for this bot. Do not assume the MCP URL is a publicly callable JSON feed. Until an official, authorized ingestion method is validated, the adapter needs a **manually prepared, normalized local JSON file**.

## Enable a local research snapshot

Prepare UTF-8 JSON at a local path (not committed to git), using this exact normalized format:

```json
{
  "schema_version": 1,
  "source": "GammaGrid",
  "exported_at": "2026-10-17T12:30:00Z",
  "symbols": [
    {
      "symbol": "SPX",
      "spot": 6500.0,
      "call_wall": 6600.0,
      "put_wall": 6400.0,
      "gamma_flip": 6450.0,
      "net_gex": -12345.0
    }
  ]
}
```

The numbers are **illustrative dummy values**, never actual market evidence. `exported_at` is the time **the operator created the JSON**, not the provider's quote timestamp. Do not simply relabel old data as fresh; the validator's 24-hour guard covers the file age, **not** underlying quote age.

Set `GAMMAGRID_RESEARCH_SNAPSHOT_PATH` to that file **only** if you have an authorized data export and can accurately map those fields. The context then contains `gammagrid_research`. If the path is missing, data are stale, records are malformed or duplicate, or there are more than 40 symbols, the adapter returns `available: false` with a reason. Oversized JSON files are refused.

**Non-negotiable limitations:**
- No data can be called live or execution-grade from this adapter.
- GammaGrid/Yahoo/yfinance are **one source family**; this is not independent confirmation.
- The snapshot is not added to the existing `sources` consensus list; its `affects_signal_score` flag remains false.
- It cannot cause CALL/PUT alerts, bypass `v11_gate`, fix missing OPRA quotes, or verify Telegram delivery.
- The bot still uses existing native GEX/Cboe and Finviz-style code. Avoid vendor-copying duplicate engines.
- No automated broker actions.

## Other GitHub candidates (not integrated by this patch)

| Project | Decision | Reason |
| --- | --- | --- |
| OpenTerminal / OpenTerminalUI | Review UI ideas | Existing dashboard/chart stack; assess data feeds and licenses before any copy |
| QuantPilot | Research screener concepts | Existing relative-volume/interest system; avoid parallel ranking and duplicate Yahoo data |
| Darthreign/gex-dashboard | Compare only | Existing SPX GEX consensus already has Cboe delayed context |
| GammaGrid MCP | Pending authorization & documented API/export contract | OAuth authorization and quote provenance not available to headless GitHub Actions |

## Verification

```bash
pytest -q tests/test_gammagrid_research.py tests/test_spx_external_gamma.py tests/test_spx_gamma_consensus.py
python -m compileall -q options_radar
ruff check options_radar/gammagrid_research.py tests/test_gammagrid_research.py
```

Full repository test suite, CI, production Telegram delivery evidence and runtime freshness must be checked separately. This patch deliberately does not claim any of those succeeded.
