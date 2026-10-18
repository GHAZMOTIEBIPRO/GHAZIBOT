# GHAZI RADAR — keyless press-wire news discovery

The free news context now uses **PR Newswire and GlobeNewswire public RSS**,
in addition to GDELT, the Fed monetary RSS, and the official BLS calendar.

## Explicit evidence levels

- SEC issuer filing = original primary regulatory filing, **only if** the
  official SEC response verified the company's current ticker/CIK. SEC access
  returned HTTP 403 on GitHub-hosted runners on 2026-10-18; do not claim it
  is healthy or silently substitute a third party as primary.
- PRNewswire/GlobeNewswire = press release distributor RSS title + original
  publisher URL, **not verified issuer-authorized press**. Even a
  stock-related press release does not establish bullish impact.
- GDELT = aggregated news *attention only*, not independent SEC confirmation.
  GDELT returned HTTP 429 on GitHub Actions; no aggressive retry.
- ClinicalTrials.gov = official study registry activity but must not be
  promoted to positive company news or issuer attribution solely on ticker.

## Safeguards

Only headlines with a curated unambiguous exact issuer name or strict
NASDAQ:/NYSE:/AMEX:/cashtag + symbol qualify as company-related RSS research.
No bare ticker matches (e.g. MU, AI or RGC), no guessing company from article
body, and no automatic issuer authentication from the distributor's domain.

Two fixed publisher feeds are queried at most once per job, sequentially,
with size and timeout bounds in the existing no-cost Company News Watch
workflow. Releases older than 7 days, invalid HTTPS publisher links, and
unparseable publication dates are excluded. Only headlines, publisher links
and source publication times are stored; full copyrighted article bodies
are not collected. HTTP restrictions and source failures are visible.

No broker orders, licensed exchange quote redistribution, secret exposure,
OPRA eligibility promotion or accuracy/win-probability claims.

## References

- https://www.prnewswire.com/rss/
- https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies
- https://github.com/underloam/xnews (Apache-2.0 feed directory; no copied code)
