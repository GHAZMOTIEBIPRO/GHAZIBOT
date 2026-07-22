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

The dashboard and data-quality branches were already merged into `main` through PRs #2, #3, and #4. New public links should therefore reference the production domain only.
