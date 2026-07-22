# Security

- Never commit brokerage keys, market-data keys, API tokens, or `.env` files.
- Configure optional data-provider credentials with GitHub Actions Repository Secrets or a local `.env`.
- The dashboard does not use email, Telegram, Discord, WhatsApp, or other outbound messaging credentials.
- If any credential appeared in Git history, revoke or rotate it; deleting the latest line is not sufficient.
- Public JSON contains status flags and analysis only, never credential values.
- The scanner never places trades. Keep execution outside this repository with explicit human confirmation.
