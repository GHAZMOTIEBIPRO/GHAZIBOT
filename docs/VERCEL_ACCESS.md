# Vercel access and public URL

## Public production URL

Use the production domain, not branch-preview URLs:

- Expected primary domain: `https://ghazibot.vercel.app`
- Vercel project: `ghazis-projects-696f16f5/ghazibot`

Confirm the exact active alias in **Vercel → ghazibot → Settings → Domains**. If Vercel assigned a different primary alias, use the domain marked **Production** there.

## Do not share preview URLs

URLs that contain `-git-<branch>-...vercel.app` are Preview Deployments. They may require Vercel login when Deployment Protection is enabled. Merging the branch does not turn the old preview URL into the production URL.

Examples that should not be used as the public link:

- `ghazibot-git-fix-data-quality-guards-...vercel.app`
- `ghazibot-git-fix-live-scan-data-...vercel.app`

## Deployment architecture

The interface and the live market data now have separate update paths:

1. GitHub Actions writes the newest scan to `public/data/latest.json` on `main`.
2. The browser requests that JSON directly from GitHub's raw-content endpoint.
3. If the GitHub request fails, the browser falls back to the copy bundled with the deployed site.
4. Vercel rebuilds only when the interface or Vercel configuration changes.

This prevents each data refresh from creating a new Vercel build. The repository-level command is configured through `vercel.json` and `scripts/vercel-ignore-build.sh`.

Important limitation: Vercel's ignored-build mechanism cancels unnecessary builds, but a canceled deployment can still count toward deployment quotas. Separating the data file from the deployed interface is therefore the main quota-saving mechanism.

## Why Render does not run the radar loop

Render serves the static dashboard through the HTTP server in `main.py`, but it does not run a permanent background scanning thread.

The scans remain in GitHub Actions because:

- free Render web services can spin down after inactivity;
- their local filesystem is ephemeral;
- repeated background scans could duplicate alerts and API requests;
- GitHub Actions already provides the controlled schedule and commits the result to `main`.

## Recommended protection setting

Keep previews protected and leave the production domain public:

1. Open **Project Settings → Deployment Protection**.
2. Use **Standard Protection** for preview and generated deployment URLs.
3. Confirm the domain marked **Production** opens without login.

Do not disable preview protection merely to publish the application. Use the production domain for public access.

## If the production domain still asks for login

1. Check **Settings → Deployment Protection** and ensure production is not included in an all-deployments protection scope.
2. Check **Settings → Domains** and confirm the primary domain points to the latest production deployment from `main`.
3. Open **Deployments**, select the latest `main` deployment, and promote it to Production if necessary.
4. Retest in an incognito browser where no Vercel session is active.

## Repository status

The dashboard, data-quality, public-serving, and deployment-efficiency changes are maintained on `main`. New public links should reference the production domain only.
