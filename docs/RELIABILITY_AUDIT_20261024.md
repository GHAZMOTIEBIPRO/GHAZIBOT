# Research reliability audit

## Scope and ownership
The existing stock-outcome-auditor is the sole writer of
`bot-state/runtime/audit_entry_fingerprints.json` and
`bot-state/runtime/public/data/reliability_report.json`.
No additional timer, market feed, Telegram message or order submission is added.
The existing source-health panel remains responsible for provider timestamps and failures.

## Data checks
Pandera 0.26.1 (MIT, pandas extra) validates identity, unique IDs, record-key match,
known outcome states, timezone-aware nonfuture signal times, finite positive entry
prices, finite optional outcome returns, and explicit research-only authority.
Missing dependency, malformed data and empty cohorts do not pass. All observations
are checked, including unavailable/ambiguous cases; failures are counted, not dropped.
It validates structure, not provider authenticity, pricing rights or predictive quality.

Official README, license, dependency metadata and open issues were reviewed on
2026-10-24: https://github.com/unionai-oss/pandera
https://pandera.readthedocs.io/en/stable/dataframe_schemas.html
This uses the installed package API, not copied upstream source. Pandera introduces
pandas/type-validation dependencies but no provider requests. Pinned version is
covered by real-package regression tests and the existing full CI suite.

## Fingerprints
SHA-256 entry fingerprints are frozen on first observation by this auditor. Outcome
changes are separate and permitted. Changed entry fingerprints set a sticky conflict;
they do not overwrite the first fingerprint. Invalid existing JSON aborts rather than
silently resetting history. Only hashes and observation metadata are stored; no raw
prices, ticker list or Telegram recipient is added to the public state repository.
This is not a cryptographically signed append-only ledger, not a retroactive proof of
signal-time capture, and not proof that a Telegram message was sent. Existing signal
tracking and delivery receipts retain their current owners.

## Statistics
QuantStats remains descriptive research on qualified decisive 60-minute events.
Fixed hypothetical round-trip costs of 0/10/25/50 bps produce mean net directional
returns and positive-after-cost fractions in the research artifact. They are not
observed spreads, commissions, execution fills, portfolio returns or an OOS validation.
Overlapping event returns cannot establish Sharpe, CAGR or maximum portfolio drawdown.
The public digest publishes statuses/counts only and withholds statistics readiness
when validation fails or any tracked entry changes. No live gates are weakened.

## Remaining dependencies
EdgarTools is already installed in research validation and requires SEC-compliant
identity and permitted source access; this change does not bypass SEC restrictions.
No licensed realtime option feed is created. Public UI expires the audit status after
72 hours and labels unavailable or insufficient samples explicitly.
