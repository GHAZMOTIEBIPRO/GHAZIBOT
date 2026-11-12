# Running the platform alpha locally

No paid service, no network and no new dependency is needed.

```bash
GHAZI_PLATFORM_ENABLED=1 \
GHAZI_PLATFORM_DEV=1 \
GHAZI_PLATFORM_INSECURE_COOKIES=1 \
GHAZI_PLATFORM_ADMIN_EMAILS=you@example.com \
GHAZI_PLATFORM_DB=var/platform.sqlite3 \
python -m ghazi_platform 8765
# open http://127.0.0.1:8765
```

| Variable | Meaning |
|---|---|
| `GHAZI_PLATFORM_ENABLED` | Feature flag. Without it every route is 404. |
| `GHAZI_PLATFORM_DEV` | Returns verification/reset tokens in the API (no mail service); the UI auto-confirms. Never in production. |
| `GHAZI_PLATFORM_INSECURE_COOKIES` | Drops the `Secure` cookie flag for plain-http localhost only. |
| `GHAZI_PLATFORM_ADMIN_EMAILS` | Comma list; these addresses become admins when they register. |
| `GHAZI_PLATFORM_BILLING_MODE` | `disabled` (default) or `sandbox`. Anything else, including `live`, is `disabled`. |
| `GHAZI_PLATFORM_BILLING_WEBHOOK_SECRET` | HMAC secret for sandbox webhooks (header `X-Ghazi-Signature`). |

Try it:
1. Register as the admin address, then as a second user (e.g. in a private window).
2. As the user: create a watchlist, add symbols, upload a daily CSV (`date,open,high,low,close,volume`),
   press «حلّل».
3. The free plan has no backtest lab; as admin open «الإدارة» and grant `pro` for 30 days.
4. As the user: «مختبر الاختبارات» → run a breakout test with an out-of-sample fraction of 0.3.

Checks:
```bash
python -m pytest -q tests/test_ghazi_platform.py
ruff check ghazi_platform tests/test_ghazi_platform.py
# with the server above running, admin = owner@example.test, fresh DB:
node scripts/platform_ui_smoke.cjs /tmp/shots
```
