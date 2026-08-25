#!/usr/bin/env bash
set -euo pipefail
if [[ "${VERCEL_ENV:-}" != "production" ]]; then echo "Skipping non-production Vercel deployment."; exit 0; fi
if ! git rev-parse --verify HEAD^ >/dev/null 2>&1; then echo "No parent commit available; allowing production build."; exit 1; fi
if git diff --quiet HEAD^ HEAD -- public/index.html public/app.js public/styles.css public/.nojekyll public/deals api/sniper.py vercel.json .vercelignore scripts/vercel-ignore-build.sh; then echo "No frontend/webhook configuration changes; skipping Vercel build."; exit 0; fi
echo "Frontend, webhook, or Vercel configuration changed; allowing production build."; exit 1
