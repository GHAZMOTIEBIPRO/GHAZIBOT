# Running the platform alpha locally

No paid service, no network and no new dependency is needed.

```bash
export GHAZI_PLATFORM_ENV=development      # required for the two dev-only flags below
export GHAZI_PLATFORM_ENABLED=1
export GHAZI_PLATFORM_DEV=1                # refused unless ENV=development
export GHAZI_PLATFORM_INSECURE_COOKIES=1   # plain-http localhost only; refused unless ENV=development
export GHAZI_PLATFORM_DB=var/platform.sqlite3
python -m ghazi_platform serve --port 8765
# open http://127.0.0.1:8765
```

| Variable | Meaning |
|---|---|
| `GHAZI_PLATFORM_ENABLED` | Feature flag. Without it every route is 404. |
| `GHAZI_PLATFORM_ENV` | `production` (default) or `development`. In production the app refuses to start with dev mode or insecure cookies. |
| `GHAZI_PLATFORM_DEV` | Returns verification/reset tokens in the API (no mail service yet); the UI auto-confirms. |
| `GHAZI_PLATFORM_INSECURE_COOKIES` | Drops `Secure` and the `__Host-` cookie prefix for plain-http localhost. |
| `GHAZI_PLATFORM_BILLING_MODE` | `disabled` (default) or `sandbox`. Anything else, including `live`, is `disabled`. |
| `GHAZI_PLATFORM_BILLING_WEBHOOK_SECRET` | HMAC secret (≥16 chars) for sandbox webhooks (header `X-Ghazi-Signature`). |

## Owner (admin) account

There is no way to become admin over HTTP. The owner:
1. registers on the site like any user;
2. confirms the e-mail (in development the UI does this automatically);
3. on the host, with the same `GHAZI_PLATFORM_DB`, runs
   `python -m ghazi_platform grant-owner --email owner@example.com`.

The command refuses an unknown or unverified address, records the grant, and signs that account out
everywhere; the owner logs in again. Admin authority needs all three: role, verified e-mail and the
recorded grant. `revoke-owner --email …` removes it and also signs the account out.

## Try it
1. Register a second user (e.g. in a private window): create a watchlist, add symbols, upload a daily
   CSV (`date,open,high,low,close,volume`), press «حلّل».
2. The free plan has no backtest lab; as the owner open «الإدارة» and grant `pro` for 30 days
   (paid plans go only to verified accounts).
3. As the user: «مختبر الاختبارات» → run a breakout test with an out-of-sample fraction of 0.3.

## Checks
```bash
python -m pytest -q tests/test_ghazi_platform.py tests/test_ghazi_platform_security.py
ruff check ghazi_platform tests/test_ghazi_platform.py tests/test_ghazi_platform_security.py
# server above running on a FRESH database, same environment variables exported:
node scripts/platform_ui_smoke.cjs /tmp/shots
```
