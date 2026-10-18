#!/usr/bin/env bash
# Vercel: exit 0 SKIPS deploy; exit 1 BUILDS.
# Only production gets a public site. PRs and bot-state stay off this project.
set -euo pipefail
if [[ "${VERCEL_ENV:-}" != "production" ]]; then
  echo "Skip non-production; the public GHAZI RADAR site uses main."
  exit 0
fi
if ! git rev-parse --verify HEAD^ >/dev/null 2>&1; then
  echo "No commit parent; build defensively."
  exit 1
fi
# Any new HTML, JS, CSS or assets in public/ must trigger a build, including
# decision-room and index-radar modules added after the old allowlist.
# Data snapshots and health metadata refresh independently from bot-state;
# they must not exhaust the free Vercel deployment quota.
# Preserve the existing /health and /data-status contract on main; these
# two tiny metadata files are part of the official status endpoints.
if ! git diff --quiet HEAD^ HEAD -- public/data/health.json public/data/data-status.json; then
  echo "New public health metadata; build the status endpoints."
  exit 1
fi
# Existing public/app.js public/index.html public/styles.css plus EVERY future
# nested frontend file now triggers a deployment.
if git diff --quiet HEAD^ HEAD -- \
  ':(glob)public/**' ':(exclude,glob)public/data/**' \
  vercel.json .vercelignore scripts/vercel-ignore-build.sh; then
  echo "Only data, tests, docs, state or backend code changed; no UI build."
  exit 0
fi
echo "Frontend asset or deployment configuration changed; build production."
exit 1
