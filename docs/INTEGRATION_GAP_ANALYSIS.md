# Integration gap analysis and roadmap (2026-11-19)

This continues `open-source-project-review.md` (2026-11-17: 572 discovered, 452 kept, 27 reviewed, 0 integrated) and
the standing decisions in `CLAUDE.md` and `OSS_SELECTION_2026-10-29.md`.
- Machine-readable decisions: `docs/data/integration_candidates_2026-11-19.json` (63 projects).
- Test evidence: `INTEGRATION_VALIDATION.md`.
- Data rights stay in `data-source-registry.md` and `provider-license-matrix.md`. They are updated, not duplicated.

**Rule applied throughout.** A project is worth adding only if it does at least one of three things, measurably:
- fixes a weakness that was observed;
- opens lawful data;
- removes risk.

Stars, popularity and feature lists are not reasons.

## 1. System inventory (observed on runners and bot-state, 2026-11-18/19)

| State | Function | Evidence |
|---|---|---|
| Working | Treasury, CFTC, DOL claims, NY Fed rates (with notice), OFR repo, USAspending, openFDA, Federal Register, company IR feeds, Wikipedia attention | `source_log.json`: 20/20 to 61/61 successful fetches each; wiki 33/33 |
| Working (owner-private) | Daily plan on Alpaca bars | 35/35 symbols, 6 frames (#450); the opening-Fibonacci digest and shadow scorecard were delivered |
| Partial | ClinicalTrials.gov | 48/61 |
| Failing, fixable by the owner | SEC EDGAR | 0/50: `NO_CONTACT_USER_AGENT` |
| Failing upstream | GDELT | 0 rows in 54 versions: HTTP 429 on shared runners, then cooldown |
| Coded, not enabled | Private options analysis (`run_focus_options_private.py`) | `BLOCKED_NO_INTERNAL_ENTITLEMENT`: `DATA_TERMS_CONFIRMED` not set |
| Coded, not enabled | edgartools adapter (`edgartools_research_adapter.py`) | needs SEC access |
| Blocked by terms (standing) | Legacy stock/options radar, SPX dashboard, index radar, classical direction, options-contract radar | Yahoo / Nasdaq.com / Cboe; heartbeat slowed (#449) |
| Never ran in a session | Private full-market scan | late crons; moved to the orchestrator (#448), first in-session check pending |
| Late | Pre-open daily plan | morning copies at 20:02Z and 19:37Z; moved to 08:30–09:20 New York (#450) |
| Research / shadow | Opening-Fib shadow, VCP/Minervini shadow, structure-liquidity shadow, quantstats shadow, explosion model lab (arch SPA), macro regimes (ruptures) | modules named `*_shadow`, research flags |
| Duplicated | EMA in 4 modules (2 seed conventions), ATR in 2, RSI in 1, VWAP inline in about 6 (2 formulas) | differential test (`INTEGRATION_VALIDATION.md`) |
| Incorrect (fixed here) | `indicators._rsi` / `_atr` warm-up | 22 % / 12.6 % off at 25 bars |
| Security gap (part fixed here) | 75 workflows | 0 SHA-pinned actions; 2 template injections; fork-PR spoof path into the Telegram watchdog |
| Weight / supply chain | Runtime requirements | 37 of 55 installed packages exist only for yfinance, yahooquery (both gated) and streamlit, including `curl-cffi` |

## 2. Gap matrix

| Area | Current function | Observed weakness | Candidate | Fix | Success test |
|---|---|---|---|---|---|
| A Data | SEC filings, Form 4, 13F, XBRL | 0/50 fetches | edgartools (adapter exists) | owner sets `SEC_USER_AGENT`; then enable the adapter | `sec_filing_pulse.json` has filings; Form 4 rows carry the accession number and filed time |
| A Data | Options analytics | no chain at all | Alpaca indicative feed (code exists); py_vollib later | owner sets `DATA_TERMS_CONFIRMED=alpaca` | `CORE Omega private scan` status is not `BLOCKED_*`; chains counted in the log |
| A Data | News attention | GDELT 0 rows | none lawful | stop calling GDELT from runners or record it as blocked; do not rotate IPs | registry status matches the runtime |
| B/C Targets and outcomes | T1/T2/T3 learning | v2 primary sample 0 (legacy invalidated) | alphalens-reloaded (IC), statsmodels | wait for matured v2 outcomes; then add IC with confidence intervals | IC with CI on ≥ 30 matured sessions; no claim before |
| D Opening Fibonacci | `opening_fib_*` | no scored sample yet | none (improve the engine, do not replace it) | keep the shadow scorecards accumulating | hit rate with a Wilson interval vs a baseline |
| E Explanations | CALL/PUT/WAIT reasons | reasons exist as fixed text | none (no LLM in the decision path) | — | — |
| F Discovery | fixed lists | the full-market scan never ran in a session | none needed | orchestrator dispatch (#448) | `Private scan: MEASURED` in session |
| G Filings and moves | catalyst watchlist | SEC blocked | edgartools | as A | as A |
| H Stability | 75 workflows | injection, spoof path, no scanning | zizmor, pip-audit, pip-licenses | pilot in this change | `security-audit.yml` green; High template-injection = 0 |
| H Stability | installs | 67 % of runtime packages unused by lawful paths | none (refactor) | lazy-import the Yahoo paths; split requirements | package count 55 → about 18 in data workflows; all tests pass |
| I UI | home summary | no historical charts of public data | DuckDB + Parquet, then Lightweight Charts | archive the public series; chart only publishable data | chart shows the source and data date |
| J Learning | indicators | duplicated implementations disagreed | pandas-ta-classic (oracle) | differential test plus Wilder fix (this change) | `test_indicator_differential.py` |

## 3. Ten strongest opportunities (ranked by value delivered per unit of risk)

| # | Opportunity | Value | Effort / risk | Status |
|---|---|---|---|---|
| 1 | SEC access: owner secret, then the existing edgartools adapter and SEC pulse | Filings, Form 4 insiders, 13F, XBRL facts; all public domain | owner: 1 minute; code exists | BLOCKED (owner) |
| 2 | Alpaca options for owner-private analysis | The only options chain available | owner: 1 variable; code exists | BLOCKED (owner) |
| 3 | Pin all 226 action references by SHA, plus Dependabot for actions | Removes tag-hijack risk in workflows that hold secrets | mechanical PR; needs online lookups | READY |
| 4 | Workflow security gate (zizmor + pip-audit + pip-licenses) | Catches injections, CVEs and copyleft before merge | done here, report-only | PILOT (this change) |
| 5 | Indicator correctness: differential test plus Wilder fix | RSI/ATR equal the reference from bar 15 | done here | PILOT (this change) |
| 6 | Requirements split and lazy Yahoo imports | 37 fewer packages per run, including `curl-cffi`; faster and smaller surface | 16 modules import at top level; medium refactor | READY_FOR_PILOT |
| 7 | One canonical indicator module | Ends duplicated EMA/ATR/VWAP code (2 EMA conventions stay explicit) | low, after #5 | READY_FOR_PILOT |
| 8 | Public-data archive (DuckDB + Parquet) built from bot-state history | History for charts, learning and audits, all lawful | low; no production writer at first | READY_FOR_PILOT |
| 9 | Charts of public series (Lightweight Charts, Apache-2.0) | Visual history of yields, claims and repo rates | after #8; attribution required | CONDITIONAL |
| 10 | Signal IC / quantile evaluation (alphalens-reloaded) | Measured edge, or measured absence of one | needs a matured v2 sample | CONDITIONAL |

Not in the ten, and why:
- **Rejected:** LLM agents in the decision path (policy); OpenBB and QuantDinger (no new data); Lean, zipline and
  nautilus (duplicate engines); FastAPI and Prometheus (no service to run).
- **Licence blockers:** vectorbt (licence unclear), backtesting.py and gammagrid (AGPL), python-telegram-bot (GPL).
- **Paid:** sec-api.

## 4. Roadmap

| Phase | Work | Precondition | Exit test |
|---|---|---|---|
| 0 (owner) | `SEC_USER_AGENT` secret; `DATA_TERMS_CONFIRMED=alpaca` if Alpaca's terms are accepted | none | settings-check reports both; SEC pulse has filings |
| 1 (this change) | Security gate; injection and spoof fixes; Wilder fix; discovery registry | — | CI green; `security-audit.yml` passes on main |
| 2 | SHA pinning plus Dependabot (actions) | phase 1 | zizmor unpinned-uses = 0 |
| 3 | Lazy Yahoo imports and a requirements split | full test suite | data workflows install about 18 packages; all green |
| 4 | Enable the edgartools adapter behind its existing research path | phase 0 SEC | Form 4 / 13F rows with accession numbers; no 403 |
| 5 | Public-data archive (DuckDB/Parquet), then charts | — | archive rebuilt reproducibly; chart shows source and date |
| 6 | IC evaluation of matured signals | ≥ 30 matured v2 sessions | IC with confidence interval published as research |

Every phase keeps the rules:
- one writer per state file;
- no competing schedulers;
- no private data in public files;
- no parameter tuning on immature samples.
