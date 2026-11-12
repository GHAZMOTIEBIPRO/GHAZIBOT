# GHAZI RADAR PRO — P0 baseline and P1 alpha (2026-11-12)

Spec: PR #424, `docs/GHAZI_RADAR_COMMERCIAL_PLATFORM_2026-11-12.md`. Status words follow AGENTS.md.

## 1. Starting point (inspected on `main` @ `cf5b9cc`)

| Area | What exists | Reused by the platform |
|---|---|---|
| Public site | Static `public/` on Vercel (`outputDirectory: public`, only `main` deploys) | Untouched. The platform UI lives in `platform_ui/`, outside the Vercel output, so it cannot be deployed by accident. |
| Telegram bot / workflows | `scripts/send_*`, 70 workflows, `bot-state` single-writer files | Untouched. The platform writes no state file and no `public/` file (tested). |
| Analysis engine | `options_radar/daily_plan.py`, `analysis_card.py` (fixed Arabic template, `numbers_supported`) | Reused unchanged, loaded by file path (no pandas import). |
| Licence guard | `options_radar/public_guard.py` | Runs on every artifact before the platform reads it. |
| Rights matrix | `data/source_rights.json` | Drives the commercial display gate (`ghazi_platform/rights.py`). |
| V11 / data fabric / learning | `v11_gate.py`, `data_fabric.py`, `omega_target_learning.py` | Not imported, not changed. |

Baseline tests on untouched `main` in this container: `pytest -q` → **1725 passed, 2 skipped**.
`scripts/bot_acceptance.py` against the live `bot-state` branch → `passed: false`
(`second_run_sends_nothing_new: false`) — **pre-existing on main**, reproduced on a clean worktree, not
caused or touched by this work.

## 2. Capability × source × commercial right × freshness (published artifacts, 2026-11-12)

"Commercial right" = `commercial_use_on_free_tier` AND `public_display_*` both `VERIFIED` in the matrix.
A signed-in platform is a commercial service even on its free plan, so UNKNOWN fails closed.

| Capability | Source in artifact | Commercial display right | Artifact age at check | Platform behaviour |
|---|---|---|---|---|
| Index / SPX reading | Yahoo (`index_radar.json`, `spx_dashboard.json`) | RESTRICTED | ~552 h (20 Oct) | NOT AVAILABLE + published reason |
| Stock rows with prices / targets | none named (`decision_brief.json`, 15 rows) | unlisted → closed | ~607 h (18 Oct) | Withheld, counted, never shown |
| Option quotes / chains | no active provider (`data-status.json`: 0 sources) | — | — | Not offered |
| Catalysts (40) | ClinicalTrials.gov | not in matrix → closed | items dated Oct | LINK_ONLY: symbol, date, official https link |
| openFDA, Federal Register, NY Fed, OFR, DOL, Treasury, USAspending | gov sources | VERIFIED | per artifact | Full text allowed when present |
| SEC EDGAR | gov | UNKNOWN in matrix | — | LINK_ONLY until the matrix records the right |
| Pipeline health | our own metadata (`health.json`) | own data | ~6 h | Shown, labelled "production time, not provider quote time" |
| Prices for analysis / backtest | **user-uploaded CSV** with a rights attestation | the user's own data, shown only to that user | as uploaded | Full analysis + backtest |

Consequence: today no market price can be shown to platform users from the repository's own feeds.
The alpha therefore works on data the user brings, and says so on screen.

## 3. P1 alpha — what is CODED and TESTED (not deployed)

Package `ghazi_platform/` (standard library only: `sqlite3`, `hashlib.scrypt`, WSGI) + `platform_ui/`.
Off unless `GHAZI_PLATFORM_ENABLED=1` (every route answers 404 otherwise).

- **Accounts:** scrypt hashes; opaque session tokens stored as SHA-256 only; HttpOnly/Secure/SameSite=Lax
  cookie; 72 h expiry; per-session CSRF token; Origin check; login lock (5 failures / 15 min per e-mail,
  30 per IP); one generic login error and equal hashing cost for unknown e-mails; single-use e-mail
  verification (48 h) and reset (1 h) tokens; password change/reset revokes other sessions; session list
  and revoke; logout everywhere.
- **Private data:** watchlists, datasets, backtests keyed by `user_id`; every query filters on the owner;
  another user's id answers 404. Export (JSON) and delete (cascade; audit rows anonymised).
- **Entitlements (server side):** plans free / plus / pro (+ admin), limits on watchlists, symbols,
  datasets, backtests per 24 h; OOS split and cost sensitivity are pro features; an expired or lapsed
  subscription falls back to free.
- **Billing:** `disabled` by default (admin grants for design partners, audited). `sandbox` mode = signed
  (HMAC-SHA256), idempotent, 5-minute-fresh webhook for activate / renew / payment failed (3-day grace) /
  cancel / expire / refund. **No live mode exists**; `live` is coerced to `disabled`.
- **Dashboard / research center:** read-only, through `public_guard` then the commercial gate.
- **Analysis:** existing engine on the user's bars; options marked NOT_LICENSED_FOR_PLATFORM.
- **Backtest lab:** EMA cross and N-day breakout, long only; entry at next open; same-bar stop+target =
  AMBIGUOUS (never a win); costs always applied; counts with denominators; no rate below 30 trades;
  time-based OOS split; cost multipliers ×0–×3.
- **Security headers:** strict CSP (self only), no framing, nosniff, no-store.

## 4. Evidence

- `tests/test_ghazi_platform.py`: 31 tests (two-user IDOR matrix over 9 endpoints, CSRF, cross-origin,
  lockout, enumeration, token single use, entitlements, lapsed plan, rights gate, artifact redaction,
  ambiguity, look-ahead, costs, webhook signature/replay/staleness, no writes to `public/`).
- Full suite with the platform: **1756 passed, 2 skipped** (1725 + 31).
- `ruff check ghazi_platform tests/test_ghazi_platform.py` clean; no repo-wide ruff finding in new files.
- `scripts/platform_ui_smoke.cjs` (Playwright, real server, iPhone 13 + 1366×900): **22/22 checks**,
  screenshots in `docs/platform_screenshots/`.

## 5. Not done / blocked (owner decisions, PR #424 §9)

- No hosting for the API: Vercel Hobby is non-commercial; a Python process host and HTTPS are needed.
- SQLite is for the alpha; PostgreSQL + backups + restore tests before real users.
- No e-mail sender: verification/reset tokens are only returned in dev mode.
- No payment processor, merchant entity, privacy policy review or CMA classification.
- No licensed price/option feed for paid display; Alpaca's public display right is RESTRICTED.
- SEC EDGAR / ClinicalTrials.gov rights are not recorded in the matrix → link-only until they are.
- Finding: `public_guard.guard_payload` raises `TypeError` when an artifact's top-level `source` is a closed
  family (e.g. `index_radar.json`); the platform handles this in its adapter. `scripts/runtime_state_vault.py`
  calls the same function and may hit it — worth a separate fix with a test.
