# Verified source recovery and task-first homepage

The public catalyst watchlist previously consumed FDA and SEC only. The existing
ClinicalTrials scanner was tied to a separate research pipeline and fuzzy sponsor
matching. This independent public adapter uses the reviewed exact normalized
issuer/sponsor index already maintained for FDA, only INDUSTRY lead sponsors, and
rejects ambiguous names, collaborators, invalid IDs, malformed and future dates.

Source research (2026-10-22 UTC / 2026-10-23 Riyadh):
- https://clinicaltrials.gov/api/v2/studies — direct live probe returned HTTP 200.
- https://catalog.data.gov/dataset/clinicaltrials-gov — NLM catalogue identifies
  public API access and ODbL. Derived registry database carries ODbL-1.0 metadata,
  NLM attribution and a public download link. No NLM endorsement claimed.
- https://www.nlm.nih.gov/databases/download/terms_and_conditions.html — attribution,
  no endorsement, currency disclosure; observed alongside the API catalogue.
- https://github.com/jvfe/pytrials — README.rst, setup.py, client.py, metadata and open
  issues inspected. BSD claimed in README/setup; GitHub reports NOASSERTION.
  Requests is its runtime dependency. Open issues discuss transport and pagination.
  No code copied and no new dependency installed; direct bounded v2 adapter selected.
- https://www.alphavantage.co/support/ — free request quota, with increased allowance
  for verified open-source/educational projects; registration/verification needed.
- https://www.alphavantage.co/terms_of_service/ and https://twelvedata.com/pricing
  plus https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage
  do not establish unrestricted public redistribution of free market quotes.
  These are candidates for licensed/private access, not activated public feeds.

Collector is capped at three pages of 250 records over a 14-day update window.
The live local probe received 750 studies and matched 207 records; PARTIAL is
explicit because a continuation token remained. These are registry observations,
not 207 actionable catalysts or a complete biotech universe. Results first-posted
is distinct from last-update date. An observed TERMINATED status does not prove
its transition occurred on the last-update date, failure of efficacy, or price direction.

The catalyst-watchlist workflow remains sole writer for its report and now also
owns runtime/public/data/clinical_registry.json. No new recurring workflow is
introduced. Retrieval errors publish sanitized diagnostics and leave independent
FDA/SEC processing running. Stale registry reports cannot enter the watchlist.
Telegram uses the existing dedupe, limits and destination; only results/status
review events qualify. Routine registry updates remain low priority. No broker
execution, quote permission or price signal gate is changed.

Homepage reference: https://updates.smartincome-17.com/ public logged-out page.
Its cream/gold action rows, stock lookup and task-first navigation were inspected
visually. GHAZI uses its own branding/copy and existing terminal controllers.
No subscriber data, performance figures, logos, backend or proprietary code copied.
The calculator remains the existing long CALL/PUT calculator with manual prices;
this is not a claim to implement covered-call/CSP/credit-spread modelling.

Validation: 1405 pytest tests passed, 2 skipped after removing test-generated local
provider circuit state. Full repository Ruff has 409 baseline findings; critical
and changed-Python Ruff gates pass. CI CLI, compileall, JS, JSON/Vercel and Omega
export gates ran successfully. New registry evidence/identity/pagination/freshness
and Telegram tests plus catalyst desk JS guards pass. Browser verified stock
search NVDA, calculator, gamma navigation, return home and 390px iframe layout.
See design-qa.md. Production verification is recorded in the PR/runtime rather
than inferred from the local probe.
