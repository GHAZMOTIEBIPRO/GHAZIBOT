#!/usr/bin/env bash
set -euo pipefail

# Preview deployments are unnecessary for this static dashboard and consume Hobby limits.
if [[ "${VERCEL_ENV:-}" != "production" ]]; then
  echo "Skipping non-production Vercel deployment."
  exit 0
fi

# A shallow clone can occasionally lack the parent commit. Build safely in that case.
if ! git rev-parse --verify HEAD^ >/dev/null 2>&1; then
  echo "No parent commit available; allowing production build."
  exit 1
fi

# Dashboard data is fetched live from GitHub, so data-only commits do not require a rebuild.
if git diff --quiet HEAD^ HEAD -- \
  public/index.html \
  public/app.js \
  public/styles.css \
  public/.nojekyll \
  vercel.json \
  .vercelignore \
  scripts/vercel-ignore-build.sh; then
  echo "No frontend configuration changes; skipping Vercel build."
  exit 0
fi

echo "Frontend or Vercel configuration changed; allowing production build."
exit 1
