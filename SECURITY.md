# Security

- Never commit brokerage keys, market-data keys, Telegram bot tokens, chat IDs,
  Discord webhooks, or `.env` files.
- Configure credentials with GitHub Actions Repository Secrets or a local `.env`.
- If a credential has appeared in Git history, revoke/rotate it. Deleting it from
  the latest file is not sufficient.
- The scanner never places trades. Keep execution in a separate least-privilege
  service with explicit human confirmation.
