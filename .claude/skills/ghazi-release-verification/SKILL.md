---
name: ghazi-release-verification
description: Verify a GHAZI RADAR change end to end after merge - source fetch on the GitHub runner, analysis output on bot-state, the public site (ghazibot.vercel.app / ghazir.vercel.app) and the Telegram bot - and report status words honestly (CODED, TESTED, CI GREEN, MERGED, RUNTIME VERIFIED, EMPIRICALLY VALIDATED). Use this whenever you are about to say something "works", "is live", "is fixed" or "is done", when a workflow succeeded but you have not looked at what it produced, when a PR merged and production must be checked, or when the user asks for evidence, run ids or a delivery report.
---

# GHAZI release verification

A green workflow can be a workflow whose steps were all skipped. A passing test can run on a fixture that production never sees. So each stage of the path is proven by the artifact it produced, read after the run, with a run id and a UTC time.

## The path and the proof for each stage

| Stage | Proof that counts | Not proof |
|---|---|---|
| Source fetch | Runner log line with the provider status, plus the output file's `generated_at` and per-source status (e.g. `usaspending_contracts.json` → `companies_ok`) | The docs page opening; an MCP connector working in this chat session |
| Analysis | The bot-state file contains the computed fields (frames, levels, events), and the commit SHA on `bot-state` | The workflow conclusion "success" |
| Site | `site-smoke` run: HTTP 200, 0 console errors per page, the new element/version present | Vercel "Ready" in a dashboard; a local build |
| Bot | Sender log: `mode`, `sent`, `eligible`, `pending`, `failed`; for private sends, the delivery status from `output_policy.deliver_private` | "Telegram step: success" (it may have sent 0) |

## Workflow

1. **Merge only on green CI** for the PR head: `Tests` plus every gate the repo runs (ui-compare). Record the merge SHA.
2. **List runs on the merge SHA.** Wait for the producers (`gh api repos/.../actions/runs?head_sha=SHA`).
3. **Check each producer's job steps.** A step that should do work must have run, not been skipped. Read the log lines that carry counts.
4. **Read the produced files** on `bot-state` (`runtime/public/data/*.json`) and check the new fields and counts.
5. **Run `site-smoke`** and read its JSON line.
6. **For the bot,** read the sender's summary line.
   - `sent: 0` with `eligible: N, pending: 0` means everything was already delivered (dedupe working). That is not a new delivery.
   - A new delivery needs `sent ≥ 1`, or a test message through the approved path.
7. **Report with status words.**
   - RUNTIME VERIFIED: only for stages whose artifacts you read.
   - EMPIRICALLY VALIDATED: only for measured signal performance on matured samples.

## Bot checks (when the bot changed)

- **Content:** the message text equals the rendered template from the real report file. No placeholders, no WAIT, no stale item.
- **Destination:** the public broadcast route vs the owner-private route. Private sends need `deliver_private` to confirm the chat is private (and the username, if set).
- **Timing:** the schedule window (e.g. Riyadh 08:15 brief), and one receipt per day.
- **Dedupe:** the same event is not sent twice across runs (the alert state on bot-state).
- **Recovery:** after a failed send, the next run retries pending items exactly once. It never re-sends items already delivered.

## Acceptance criteria

- Every claim in the delivery report has a run id and a UTC time, or a file path on bot-state with its `generated_at`.
- CI success is never presented as production success.
- Blockers name the exact missing setting (secret or variable name) and where to add it. Values are never requested or printed.

## Examples

**Pass:** "Catalyst run 40795773695 (00:42–00:45 UTC):
- USAspending: 10/10 companies OK, 67 actions;
- catalyst list: 2 GOV_CONTRACT_ACTION events (bot-state commit 8db4d1ed);
- Telegram: eligible 9, sent 0, pending 0, so already delivered and no duplicates;
- site-smoke 40796190650: 10 pages HTTP 200, 0 errors."

**Fail:**
- "Deployed and working ✅" with no run id.
- "Telegram sent" based on a successful step that sent 0.
- "Leaders analysis restored" when the private plan reason is `ACCOUNT_CREDENTIALS_NOT_CONFIGURED`.

## Where things live

| Code | Role |
|---|---|
| `scripts/site_smoke.cjs`, `.github/workflows/site-smoke.yml` | Site checks |
| `scripts/ux_tasks.cjs`, `.github/workflows/ui-compare.yml` | User-task checks on rebuilt data |
| `scripts/check_settings.py`, `.github/workflows/settings-check.yml` | Settings presence and types only |
| `scripts/send_catalyst_watchlist_alerts.py` | Public alert dedupe and receipts |
| `options_radar/output_policy.py` | Private route |
