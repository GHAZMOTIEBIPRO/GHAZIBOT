# CLAUDE.md — working notes for coding agents

`AGENTS.md` is the engineering contract; this file only records standing decisions and the commands
that verify work. Progress of the current mission: `docs/PROGRESS.md`.

## Standing decisions (do not reopen without new evidence)
- **Prices.** The only lawful automated bar source is Alpaca (owner-private). It needs:
  - secrets `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`;
  - variable `ALPACA_INTERNAL_DATA_USE_AUTHORIZED=true`.

  Yahoo/yfinance/yahooquery, Nasdaq.com, Stooq and Cboe pages stay gated by their terms (see
  `docs/PRICE_SOURCE_INVESTIGATION_2026-10-25.md`). Do not re-enable automated Cboe collection.
- **Gated sources.** BLS and FRED automation stay gated (`options_radar/source_permissions.py`): the
  terms could not be verified from the runner, and FRED's API terms forbid storing.
- **An attestation variable is the owner's record, not provider permission.**
  - A key being present is not permission to use it.
  - An MCP connector in an assistant session is not a GitHub Actions credential.
  - Installed plugins (`.claude/settings.json`) do not make paid data connectors available.
- **No look-ahead.** Store the publisher's own publication / vintage time next to the observation.
- **Analysis.** Computed in code (`options_radar/daily_plan.py`, `analysis_card.py`).
  - The Arabic text is a fixed template over computed facts, with no model call.
  - SPX is kept apart from SPY, and stock price apart from contract price.
- **Libraries** (`docs/OSS_SELECTION_2026-10-29.md`):
  - pandera: in use.
  - pandas-ta-classic: the indicator reference.
  - TA-Lib: not added (C build).
  - backtesting.py: AGPL, not integrated.
  - Playwright: in use.
- **State.** One writer per state file on `bot-state`; probes print to the log only.

## Verify (what CI runs)
```
pytest -q
ruff check .
python -m compileall -q main.py export_web.py run_live_export.py options_radar scripts
node --check public/radar.js
node tests/radar_ui.cjs          # UI unit checks
node scripts/ux_tasks.cjs        # Playwright tasks (needs a local server; see ui-compare.yml)
python scripts/bot_acceptance.py # offline bot acceptance on real outputs
```
- Explicit file lists bypass ruff's `extend-exclude`, so add `--force-exclude`.
- Vendored skills under `.claude/skills/` are excluded.

## Runner checks (log-only, branch push)
- `settings-check.yml` reports which secrets and variables reach a job: booleans and value classes only.
- `macro-sources-probe.yml` covers OFR, NY Fed, Fed DDP and DOL: terms and data structure.
- `live-platform-probe.yml` checks that the live sites serve the platform card.
- `sec-access-probe.yml` runs `scripts/probe_terms.py` for terms pages.

## Shell-hook limits in this environment
- No heredocs, no inline multi-statement `python -c`, at most 10 command separators.
- Write scripts to files instead.
