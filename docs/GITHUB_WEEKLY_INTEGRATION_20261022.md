# GitHub catalogue review and completed-week context — 2026-10-22

## What was actually inspected

Repository metadata (identity, last push, archive flag and reported license) was retrieved for all 34 previously resolved entries. Three additional matching candidates were identified through GitHub search/README review: SamPom100/UnusualVolumeDetector (MIT), mfdeux/unusualvolume (MIT, last push 2020), and rgaveiga/optionlab (GPL-3.0). There are now 37 repository links and 13 unresolved generic titles in the 50-name catalogue. A matching candidate is not proof of the original author's intended link.

The metadata snapshot is `docs/github_37_metadata_20261022.json`. GitHub's NOASSERTION is unresolved classification, not permission to copy. Repository stars/activity do not establish trading performance. This is not a full security audit of 37 codebases.

Detailed functional inspection: Qullamaggie README, MIT LICENSE, requirements, `scanner/factors/weekly.py` and open issue/PR listing; Stock Screener README and stack; OptionLab README/license metadata; unusualvolume READMEs. Qullamaggie has an open fund/ETF-universe filtering PR, another reason not to replace the existing stock identity controls with upstream code wholesale.

## New functionality

`options_radar/weekly_setup_shadow.py` is an independently written weekly-context implementation, inspired by Qullamaggie's daily/weekly comparison. No upstream code or dependencies are copied. It is called by the existing `vcp_trend_shadow`, so both the public chart path and authorized private Alpaca research path compute the context from their already-acquired complete daily bars.

- Require 12 consecutive completed weekly aggregates; use New York session dates and the XNYS calendar to reject missing/extra sessions. Do not interpolate missing prices.
- Exclude a week whose Friday is later than the last supplied complete daily bar. A Friday holiday is deliberately deferred until the next source session.
- Compare the mean true range of the last 3 weeks with the prior 3 (non-overlapping); compression threshold is 0.85.
- Trend: latest weekly close above the 10-week mean and that mean above its preceding value.
- Weekly breakout is descriptive: close above the preceding 4-week high, excluding the evaluated week.
- `DAILY_WEEKLY_ALIGNED` requires the existing daily TIGHT_WATCH plus weekly trend and compression. It does not alter daily rank, alert eligibility, V11, provider identity, or confidence scores.
- Arabic stock cards show same-source weekly context only with permitted, non-historical Yahoo public research. Private Alpaca bars/results are not newly exported to the public website.

This differs deliberately from upstream's overlapping 3/10 ATR ratio and does not inherit its reported results. No return/accuracy claim. Scope is price/volume research, not full CANSLIM, all Minervini rules, or institutional positioning.

## Catalogue corrections

OptionLab is now a concrete GPL-3.0 candidate marked for license review, not silently installed. Unusual Volume Detector and unusualvolume are identified references; our existing volume algorithm remains independent. QuantStats is accurately marked as an existing optional integration, with a link to its signal-outcome adapter; no portfolio-return claim.

## Reproduction and runtime limits

Run `pytest -q`, `node tests/terminal_weekly_setup.cjs`, `node tests/terminal_github_projects.cjs`, and the actual CI gates. Tests cover partial-week lookahead, XNYS holidays, a missing session, malformed bars, pipeline current-day exclusion, and UI authority/source restrictions.

Longer historical Alpaca connector probes in this session returned an internal tool error; no successful real-market weekly run is claimed from those calls. Production's pre-existing source authorization/credential gates remain unchanged. When no permitted OHLC exists, the weekly feature is unavailable rather than invented. CI and source publication do not prove live feed readiness or an empirically profitable signal.
