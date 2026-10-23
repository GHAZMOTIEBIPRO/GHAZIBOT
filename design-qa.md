# GHAZI task-first homepage review

- Source visual truth: https://updates.smartincome-17.com/ (public logged-out homepage),
  capture /workspace/scratch/ghazi-reference-20261023.png.
- Implementation: http://terminal.local:4173/, capture
  /workspace/scratch/ghazi-start-20261023.png.
- Viewport: both desktop captures 1348 x 926, matching browser viewport, no density
  scaling. Additional 390 x 844 embedded viewport inspected in the cloud browser.
- State: light homepage, no source login; source tour dismissed. Both source and
  implementation screenshots returned together in the same comparison tool result.

## Findings and comparison history

- P1 functional issue in first iteration: submitting NVDA initially let a scheduled
  render restore SPX. Fixed by selecting the symbol through chooseChart and
  refreshSymbols. Browser re-tested and visible TradingView status read NVDA.
- Final comparison: no actionable P0/P1/P2 visual issues. Intentional differences:
  GHAZI branding, own research copy, no subscription/Telegram promo panel, a short
  branded hero before the primary stock search, and existing dark terminal when
  opened. This is a reference-inspired redesign, not a pixel clone.
- Typography: existing Noto Sans Arabic retained; clear headings and form controls,
  readable RTL labels, LTR ticker. No clipped headings at the tested sizes.
- Spacing/layout: cream action rows, two desktop columns, stacked mobile layout;
  no mobile horizontal overflow observed; buttons/field fit within 390px viewport.
- Colors: cream/white, restrained gold, dark text and visible focus outlines.
- Image/asset quality: no source logo or image used; existing GHAZI wordmark text.
  This is a data/UI surface with no generated or placeholder imagery.
- Copy/content: own descriptions state data availability; no imported performance
  claims or claim to detect actual institutional purchases.
- Focused review: stock input/action row and 390px mobile capture inspected; full
  captures have readable headings/buttons. Nav actions, NVDA search, existing
  calculator visibility, gamma unavailable state and home navigation tested.
- Console checked: sampled errors came from the browser extension content script;
  no application JavaScript exception observed in that sample. Data-source gaps
  and unavailable quotes remain visible and are not presented as UI success.

## Follow-up polish

- P3: extend the lighter palette to the older advanced analysis views in a later
  scoped change; retaining their proven controls reduces regression risk.
- Third-party TradingView data loading remains dependent on provider availability.

final result: passed
