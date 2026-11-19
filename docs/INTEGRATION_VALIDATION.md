# Integration validation (2026-11-19)

What was actually run for the two pilots chosen in `INTEGRATION_GAP_ANALYSIS.md`, with results, and what is
still unverified. Status words follow AGENTS.md.

## Pilot 1: supply-chain and workflow security (zizmor, pip-audit, pip-licenses)

**Why this pilot.** The repository had no security scanning at all:
- 75 workflows, many holding the Alpaca and Telegram secrets;
- all 226 action references pinned by tag, none by SHA;
- 16 workflows triggered by `workflow_run` or `pull_request_target`.

All three tools are free and permissive (zizmor MIT, pip-audit Apache-2.0, pip-licenses MIT). They read files and
package metadata only, and touch no market data.

**Run here** (pinned versions zizmor 1.32.0, pip-audit 2.10.1, pip-licenses 5.5.5):

| Check | Result |
|---|---|
| zizmor `--offline` over `.github/workflows` | 370 findings: unpinned-uses 226, artipacked 107, dangerous-triggers 13, informational template-injection 8, self-repository 6, adhoc-packages 5, excessive-permissions 3, **High template-injection 2** |
| pip-audit `-r requirements.txt` | 54 runtime packages checked, **0 known vulnerabilities** |
| pip-licenses over a runtime-only venv | 55 packages: 52 permissive, 2 MPL-2.0 (certifi, tqdm), 1 UNKNOWN (peewee, which comes in through yfinance), **0 GPL/AGPL** |

### Findings triaged and fixed in this change

1. **`stock-radar.yml`: real command injection (High).**
   - `inputs.source_run_id` was substituted into the shell script *before* the script's own digits-only check, so the
     check could not stop it.
   - Exploiting it needs write access to the repository (workflow_dispatch).
   - Fix: the value now arrives through `env` (`SOURCE_RUN_ID`) and is still validated.
2. **`options-radar.yml`: flagged High, low real risk.**
   - `github.event.schedule` comes from the workflow file itself.
   - It now goes through `env` too, for consistency.
3. **`telegram-failure-watchdog.yml`: spoofed alerts (one of the 13 dangerous-triggers).**
   - The watchdog runs after `classical-direction-radar.yml`, which also runs on `pull_request`.
   - Its guard was `head_branch == 'main'`. A pull request from a fork's own `main` branch also has that value.
   - What was **not** exposed: secrets. The watchdog checks out `main`, and it downloads the Telegram connection
     artifact only from workflows that never run on pull requests.
   - The remaining risk was a misleading failure or recovery message to the owner.
   - Fix: the guard now also requires `head_repository.full_name == github.repository` and
     `event != 'pull_request'`.

Workflow-run artifact review, all 13 `workflow_run` consumers:
- Each consumer's upstream workflows were compared with the workflows that run on `pull_request` or
  `pull_request_target`.
- That set is test.yml, classical-direction-radar.yml, company-news-watch.yml, open-source-model-validation.yml and
  security-audit.yml.
- Only the watchdog has such an upstream. No other consumer can be started by a pull request.

**What runs from now on.** `security-audit.yml` is a new workflow:
- triggers: pull requests and pushes to main that touch workflows or requirements, plus manual runs;
- read-only token, no secrets, `persist-credentials: false`.

`scripts/security_audit_summary.py` writes the step summary. It is report-only, except for three things that block:
- a High-severity template injection;
- a GPL or AGPL runtime dependency;
- an unreadable zizmor report (the gate fails closed when it cannot see).

**Tests:**
- `tests/test_security_audit_summary.py` (4);
- `tests/test_telegram_failure_watchdog.py` (fork guard);
- `tests/test_telegram_direct_delivery.py`, whose pin moved from the vulnerable pattern to the env form.

After the fixes the gate passes locally: High template-injection 2 → 0.

**Status:** CODED · TESTED. CI GREEN, MERGED and RUNTIME VERIFIED are recorded in the PR once they happen.

**Not done, and why:**
- **Pinning 226 action references by SHA** needs an online lookup per action and touches every workflow. It is a
  separate, mechanical PR (roadmap item 3).
- **artipacked (107):** most of these jobs push to `bot-state` with the persisted token, so
  `persist-credentials: false` cannot be applied blindly.

## Pilot 2: indicator differential test (pandas-ta-classic as the oracle)

**Why this pilot.** EMA, ATR, RSI and VWAP are implemented separately in several modules:
- EMA in 4 places;
- ATR in 2 places;
- VWAP inline in about 6 places, with two different formulas.

The existing parity test covered only `daily_plan.ema` and `daily_plan.atr`. pandas-ta-classic is already the
indicator reference (MIT, dev dependency), so this adds no dependency. TA-Lib stays out (standing decision); the
reference's RMA documents TA-Lib parity.

**Method:**
- one fixed-seed random-walk OHLCV series;
- every implementation compared on the last value, at 25, 40, 60, 100 and 250 bars;
- results are relative errors.

| Implementation | Before | After |
|---|---|---|
| `indicators._rsi` (RSI14) | 22 % at 25 bars · 6.9 % at 40 · 2.3 % at 60 · 0.07 % at 100 | ≤ 2e-16 at every length |
| `indicators._atr` (ATR14) | 12.6 % at 25 · 4.2 % at 40 · 1.0 % at 60 · 0.05 % at 100 | 0 at every length |
| `daily_plan.atr` | ≤ 5e-16 | unchanged |
| EMA, first-value seed (`daily_plan.ema`, `indicators._ema`) | equal to `ta.ema(sma=False)` | unchanged |
| EMA, SMA seed (`core_options._ema`, `vcp._ema`) | equal to `ta.ema()` | unchanged |
| EMA, family vs family | up to 0.6 % (EMA21 at 25 bars), under 1e-5 from about 5× span | documented, not changed |
| Session VWAP (typical price) | equal to `ta.vwap(anchor="D")` | unchanged |
| `build_spx_dashboard` VWAP (close-weighted, labelled as such) | 0.06 % from the typical-price VWAP | labelled already; unchanged |

**Root cause.** The two indicators in `indicators.py` ran Wilder smoothing as a plain `ewm` seeded with the first
value. Wilder's definition, and TA-Lib, seed with the average of the first 14 values. The error fades only after
about 100 bars.

**Fix.** `_wilder()` uses the SMA seed, after the first valid value. The first true range is undefined, because
there is no previous close.

**Impact.**
- `analyze_technical` requires 60 bars, where RSI was off by about 2.3 % (about 1.2 RSI points near 50). That can
  flip its 52–75 and 25–48 bands at the edges.
- Its callers, `stocks.py`, `scanner.py` and `runtime_hardening.py`, sit on the Yahoo-gated legacy path. So no
  delivered alert used the faulty value in the current state.
- The fix matters as soon as that path gets a lawful source.

**Tests.** `tests/test_indicator_differential.py` (10):
- RSI and ATR equal the reference from 25 to 250 bars;
- nothing is reported before the seed;
- each EMA family equals its own reference;
- VWAP equals the reference.

Full suite: 1847 passed, 2 skipped.

**Status:** CODED · TESTED.

## Discovery evidence (inputs to the registry)

| Step | What was done | Output |
|---|---|---|
| Seed list from the brief (groups A–H plus the tools above) | `oss_review.py verify`: exact `repo:` searches, 6 per query | 56 of 56 resolved; 1 redirect (OpenBB → openbq-org/OpenBB) — `docs/data/oss_seed_verified_2026-11-19.json` |
| New categories | `oss_review.py fetch --extended`: 22 categories, 23 queries | 124 repositories, 108 kept after the screen — `docs/data/oss_candidates_extended_2026-11-19.json` |
| Licence cross-check for unclear GitHub licences | PyPI JSON metadata | arch: NCSA (permissive) · openbb: Apache-2.0 · vectorbt: no licence declared (Commons Clause per project) |
| Usage in this repository | grep of requirements and imports | Already present: edgartools (adapter), ruptures (`macro_regimes.py`), arch (SPA test), alpaca-py (stream), quantstats, pandera, pandas-ta-classic, exchange_calendars, playwright |
| Decisions | `scripts/build_integration_registry.py` | 63 recorded decisions — `docs/data/integration_candidates_2026-11-19.json` |

## Not verified

- **External code read:** only pandas-ta-classic (RMA source) and the three audit tools, which were run.
  - Every other project is judged on metadata, its own description, and its use in this repository. The registry
    records the evidence level per row.
  - No external project was audited for security.
- **Search coverage:** GitHub search returns the most-starred matches per query. It does not cover all of GitHub,
  and some categories (gap scanners, hit probability) returned few relevant projects.
- **Results of the extended sweep:** many are generic machine-learning tools. Their decisions apply to the ones
  recorded only.
