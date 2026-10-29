# Skills in this directory

Claude Code loads project skills from `.claude/skills/<name>/SKILL.md`.
- Only a skill's name and description sit in context all the time.
- The skill's body and files are read only when a task calls for it.

## Vendored official skills (unchanged copies)

| Skill | Source | Commit | Licence | How this project uses it |
|---|---|---|---|---|
| `frontend-design` | [anthropics/skills](https://github.com/anthropics/skills/tree/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design) | `ca45fc496a3436251f191354091d557da31c15b5` (2026-10-28) | Apache-2.0 (`LICENSE.txt` kept) | See below. |
| `webapp-testing` | [anthropics/skills](https://github.com/anthropics/skills/tree/ca45fc496a3436251f191354091d557da31c15b5/skills/webapp-testing) | same | Apache-2.0 | See below. |
| `skill-creator` | [anthropics/skills](https://github.com/anthropics/skills/tree/ca45fc496a3436251f191354091d557da31c15b5/skills/skill-creator) | same | Apache-2.0 | See below. |

### `frontend-design`
- Used when changing `public/` pages.
- Its two-pass process (token plan → review against the brief → build → screenshot critique) is applied to the GHAZI brief. The brief is Arabic RTL, calm contrast, never red/green alone, and the chart early.
- The brief's own rules win where they fix a direction.

### `webapp-testing`
- Its pattern is followed in `scripts/ux_tasks.cjs`: wait for the app, reconnoitre, then act. The repo's Playwright is Node, and the pre-installed Chromium is used as-is.
- `scripts/with_server.py` is not needed, because the UX runner starts its own static server.

### `skill-creator`
- Used to write the four project skills below. It sets the anatomy (frontmatter, under 500 lines, references loaded on demand) and requires test prompts in `evals/evals.json`.
- `run_loop.py` / `run_eval.py` call `claude -p`. They are not run in CI.

### Updating a vendored skill
1. Re-copy the skill from a newer commit.
2. Update the commit in the table above.
3. Review the diff of its scripts before running any of them.

## Plugins enabled at project scope (`.claude/settings.json`)

| Plugin | Marketplace | Commit | Licence | Note |
|---|---|---|---|---|
| `financial-analysis`, `equity-research`, `market-researcher` | [anthropics/financial-services](https://github.com/anthropics/financial-services) | `60565064557ca77b12f62aa7877f365d111c129d` | Apache-2.0 | Hooks are empty. |

- `financial-analysis` declares MCP servers that need paid accounts: Daloopa, Morningstar, S&P Global, FactSet, Moody's, MT Newswires, Aiera, LSEG, PitchBook, Chronograph and others.
- None of those accounts exist here. Installing the plugin gives no data access, and GitHub Actions never has these connectors.
- Only the skills' methods are used: report structure, and checks on comparables and earnings reviews.

## Reviewed, not vendored

| Skill | Source | Commit | Licence | Use |
|---|---|---|---|---|
| `web-design-guidelines` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | `1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62` | MIT | Its rules file (`vercel-labs/web-interface-guidelines` `command.md`) is applied by hand to `public/`. |

- The skill fetches its rules at run time, so it is not copied here.
- The React skills from the same repo do not apply: the site is plain JavaScript.

## Project skills (written here with skill-creator)

| Skill | Job |
|---|---|
| `ghazi-data-quality` | Source, freshness, gaps, duplicates, time zones, splits/adjustment. Data errors kept apart from compute errors and from an unavailable source. |
| `ghazi-market-analysis` | Multi-frame reading from reproducible computations. Observed facts kept apart from interpretation and scenario. |
| `ghazi-options-evidence` | Chain validity, liquidity, spreads, OI timing. No inferred trade direction or trader identity. |
| `ghazi-release-verification` | Data → analysis → site → bot, proven per stage. A passing test kept apart from a real production run. |

Each project skill has `evals/evals.json` with pass and fail examples.
