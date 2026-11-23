# GHAZI RADAR PRO — Alpha → Beta technical plan (2026-11-12)

Starting point: PR #425 at `fa0bf4e` (alpha, feature-flagged, CI green, not deployed).
Beta = up to ~50 invited design partners on a real HTTPS host, with real e-mail, PostgreSQL, monitoring,
and admin tooling. **Still no real money, no licensed price feed, no production promotion without the
owner's approval.** Every item below names its files, tests and acceptance; nothing is "done" until its
acceptance test runs in CI.

## 0. Owner decisions needed before work that costs money (one list)

| # | Decision | Options (none bought yet) | Blocks |
|---|---|---|---|
| D1 | Host for the Python service | Container on Fly.io / Render / Railway, or a VM (Hetzner, AWS Lightsail) behind Caddy. Region close to KSA users (e.g. Bahrain `me-south-1`, Frankfurt) | W3 |
| D2 | Managed PostgreSQL | Same provider as D1, or Neon / Supabase / AWS RDS. Needs point-in-time recovery | W1 |
| D3 | Transactional e-mail | Amazon SES, Postmark or Resend; a sending domain the owner controls (SPF, DKIM, DMARC) | W2 |
| D4 | Error tracking | Sentry (hosted, free tier) or self-hosted GlitchTip | W4 |
| D5 | Domain for the app | e.g. `app.<owner-domain>`; the static site stays on Vercel unchanged | W3 |
| D6 | Legal | Privacy policy + terms reviewed; CMA classification of the research service | Beta invite |

Monthly spend ceiling to be set by the owner before D1–D4; each provider adapter ships with a free/dev
fallback so CI never needs a paid account.

## W1 — PostgreSQL (replaces SQLite for deployed environments)

Design: keep `ghazi_platform/db.py` as the only SQL entry point; add a PostgreSQL backend behind the same
`tx() / query() / one()` interface. SQLite remains for tests and local dev.

1. `ghazi_platform/migrations/0001_initial.sql …` numbered, forward-only; table `schema_migrations`;
   `python -m ghazi_platform migrate`. Replaces `SCHEMA` + `_ADDED_COLUMNS`.
2. Driver: `psycopg[binary]` 3.x (LGPL-3.0, used as a library: compatible; record in
   `docs/OSS_SELECTION_*`). Placeholder translation `?`→`%s` in one function, tested.
3. Locking: SQLite's `BEGIN IMMEDIATE` becomes, in PostgreSQL, `SELECT … FROM users WHERE id=%s FOR UPDATE`
   at the start of every limit-checked transaction (per-user lock, no global lock).
4. Row-level security as a second wall: `ALTER TABLE watchlists ENABLE ROW LEVEL SECURITY` with policy
   `user_id = current_setting('app.user_id')::int`; the app sets `SET LOCAL app.user_id` per request; the app
   role is not the table owner. Queries keep their explicit `user_id` filter (first wall).
5. Backups: provider PITR + a nightly `pg_dump` to encrypted storage; a weekly CI job restores the latest
   dump into a throwaway database and runs the isolation tests against it.

Tests / acceptance
- Run the whole `tests/test_ghazi_platform*.py` suite against both backends (pytest parametrised fixture;
  PostgreSQL via a `services: postgres` container in a new `platform-db.yml` workflow — free on GitHub).
- New: RLS test that connects as the app role, sets `app.user_id` to Bob and must read 0 of Alice's rows
  even with a query that omits the `user_id` filter.
- Concurrency tests (`test_concurrent_*`) pass on PostgreSQL with 8 processes.
- Restore drill job green once per week; restore time recorded.

## W2 — E-mail (verification, reset, security notices)

1. `ghazi_platform/mailer.py`: interface `send(to, template, context)`; backends `ConsoleMailer` (dev,
   prints a redacted link), `SMTPMailer` / provider API (prod). Config `GHAZI_PLATFORM_MAIL_BACKEND`;
   production refuses to start with the console backend (same pattern as `Config.validate`).
2. Links, not tokens in the API: `https://app…/#verify?token=…`; remove `dev_*` fields from responses in
   every environment except tests; the UI reads the token from the URL fragment (never sent to logs).
3. Arabic templates (plain text + HTML) in `ghazi_platform/templates/`: verify, reset, password changed,
   new sign-in, account deleted, plan changed.
4. Outbound queue table `outbox(id, to_hash, template, payload_json, attempts, next_at, sent_at)` with a
   worker command `python -m ghazi_platform send-mail`; bounded retries; a send failure never blocks sign-up.
5. Deliverability: SPF, DKIM, DMARC on the sending domain; bounce/complaint webhook marks the address.

Tests / acceptance
- Unit: each template renders with only its context (no user data from other accounts); links use the
  configured base URL; a log capture during a full sign-up/reset flow contains no token.
- `send-mail` retries then gives up after N attempts and records it.
- Manual: one real verification e-mail received on Gmail and Outlook with SPF/DKIM pass (owner checks).

## W3 — Commercial hosting

1. `Dockerfile` (python:3.12-slim, non-root user, read-only FS except `/tmp`), `gunicorn` (MIT) with
   `ghazi_platform.web:create_app()`; 2–4 workers.
2. TLS at the edge (provider or Caddy); HSTS header added by the app when `environment=production`.
3. Trusted proxy: `GHAZI_PLATFORM_TRUSTED_PROXIES` (CIDR list). Only then is `X-Forwarded-For` used for
   `req.ip`; otherwise `REMOTE_ADDR`. Fixes the per-IP rate-limit limitation noted in the alpha.
4. Health endpoints: `/api/health` (no DB) and `/api/ready` (DB round-trip + migrations current).
5. Environments: `staging` (seeded fake users, sandbox billing) and `production`; deploy from a tag via a
   workflow that needs a manual approval (GitHub environment protection). `main` merges do not deploy.
6. Secrets only in the host's secret store (DB URL, mail key, webhook secret, Sentry DSN); `settings-check`
   style job prints booleans only.
7. Read-only research artifacts: the service fetches `public/data/*.json` from the existing `bot-state`
   raw URLs on a schedule into a local cache (one reader, no writer), still passed through
   `public_guard` + the rights gate.

Tests / acceptance
- Container builds in CI; `docker run` + `scripts/platform_ui_smoke.cjs` against it passes (25 checks).
- OWASP ZAP baseline scan (Apache-2.0, GitHub Action) against staging: no High findings.
- `curl -I` shows HSTS, CSP, `__Host-` cookie with Secure; HTTP redirects to HTTPS.
- Rollback rehearsal: deploy previous tag, readiness green, recorded in the PR.

## W4 — Monitoring and incident response

1. Structured JSON logs (method, path template, status, duration, user id hash, request id). A unit test
   feeds a request containing a token, password and e-mail and asserts none appears in the log line.
2. Error tracking (D4) with a `before_send` scrubber that drops request bodies, cookies, headers and
   query strings; release = git SHA.
3. Uptime checks on `/api/ready` every minute from two regions; alert to the owner (e-mail + the owner's
   existing private Telegram chat via a separate bot token, not the market bot).
4. Metrics: sign-ups, verified %, logins failed/locked, 4xx/5xx rate, p95 latency, backtest queue time,
   artifact cache age. Weekly digest to the owner.
5. Runbook `docs/PLATFORM_RUNBOOK.md`: DB down, mail provider down, artifact cache stale, credential leak
   (rotate + revoke all sessions command), suspected account takeover.

Acceptance: a deliberately raised error on staging appears in the tracker with no request data; stopping
the DB triggers an alert within 3 minutes; the runbook's "revoke all sessions" command works on staging.

## W5 — User management and admin hardening

1. Admin MFA (TOTP, RFC 6238, standard library HMAC): required for every `access == "admin"` route;
   enrolment via the `grant-owner` CLI (prints the secret once as a QR in the terminal); recovery codes.
2. Re-authentication for sensitive admin actions (plan grant, suspend, delete): password + TOTP within the
   last 10 minutes.
3. User states: `active | suspended | deleted`; `suspend` revokes sessions and blocks login with a neutral
   message; admin UI search by e-mail, view plan/history, resend verification, force sign-out.
4. Optional user MFA (TOTP) for everyone; new-sign-in e-mail (W2).
5. Account e-mail change with verification of the new address and a notice to the old one.
6. Session list shows approximate device + last IP (truncated /24) for the user.

Tests: admin route without fresh TOTP → 403; suspended user cannot log in and has 0 live sessions;
e-mail change cannot take over an address another account holds; IDOR matrix extended to the new routes.

## W6 — Product items for design partners (no new data rights needed)

- Watchlist → research center filter per symbol, CSV import/export of watchlists.
- Saved backtest configurations; compare two runs; download results (CSV) for pro.
- Rights matrix updates by the owner for SEC EDGAR and ClinicalTrials.gov (terms read on the runner like
  OFR/DOL) — the gate shows text automatically once recorded VERIFIED.
- Accessibility pass (keyboard, contrast, screen reader labels) with axe-core in the Playwright smoke.

## Order and exit criteria

1. W1 + W5(MFA) in parallel → 2. W2 → 3. W3 staging → 4. W4 → 5. invite 5 design partners on staging →
6. owner approval → production.

Beta exit (all must hold, each with evidence in a PR): CI green including PostgreSQL + RLS + concurrency;
ZAP baseline no High; restore drill green; admin MFA enforced; real e-mail flow verified; monitoring alert
drill done; privacy policy/terms approved by the owner's counsel; no price or option value shown without
a VERIFIED commercial right; still no live billing.
