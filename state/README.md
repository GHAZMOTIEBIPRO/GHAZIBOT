# BLACK BOX Omega Durable State

This branch is machine-managed durable state for the autonomous radar.

Rules:
- No API keys, tokens, passwords, credentials, or Telegram secrets.
- Only validated non-secret runtime state may be committed under `state/`.
- `state/options/` stores guarded options-learning continuity.
- `state/performance/` stores performance-auditor notification continuity.
- State commits use `[skip ci]` and never change trading decision code.
- GitHub Actions artifacts remain a hot-state/backup layer; this branch is the durable fallback.
