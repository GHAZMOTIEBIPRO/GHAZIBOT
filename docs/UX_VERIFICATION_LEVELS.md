# What the automated UX tasks prove, and what they don't

`scripts/ux_tasks.cjs` runs real Chromium against the page (phone 390×844 and desktop 1440×900, both Arabic). The task count is not usability evidence.

**Three levels are kept apart:**
1. **Shown:** the element or text is on screen.
2. **Correct:** what is shown matches the published data or the arithmetic.
3. **Understood:** a person reads it and draws the right conclusion. **No task measures level 3.** No user study has been run. "33/33 passed" means 33 scripted checks of levels 1–2, not that users understand the page.

**Cross-origin charts:**
- A chart frame that loaded proves only that TradingView's frame loaded.
- The browser does not let the page read the frame's content. Symbol, interval and "symbol not found" messages inside it are TradingView's and are **not verified**.

| Task | Level checked | Not checked |
|---|---|---|
| find a stock by company name (keyboard only) | 1–2: suggestion list, Enter opens the right symbol | — |
| understand why it appears | 1: at least one reason line, 16px | 2: reason correct for the data (covered only by unit tests of the row builders); 3: understood |
| analysis availability is stated | 1: the price-analysis state sentence is present | Whether the stated state is current (the data files decide) |
| change the chart frame | 1: the 1H button is pressed and a chart state (ready / timeout / failed) is shown | That the chart loaded (**passes on "failed"**), that it shows 1H, or that its content is right |
| Arabic search | 2: «انفيديا» finds NVDA | — |
| valid symbol outside S&P 500 | 2: opens with the listing from Nasdaq's file | — |
| unknown valid symbol | 2: marked unverified, no company name invented | — |
| open the original news | 1: the first news link points to its official source | That the link resolves (HEAD often blocked from the runner; status recorded, not required) |
| Federal Register notices not tied to a stock | 1: rows shown | Relevance to a stock (none is claimed) |
| catalysts tab and Nasdaq listing flags | 1–2: flag rows and wording | That the user reads a flag as "not a delisting decision" |
| Federal Register risk event on the stock page | 1: the official link is shown | Impact (shown as needing assessment) |
| phone back button / Escape / scroll per tab | 2: behaviour (panel closes, position kept) | — |
| app sections: radar, watchlist, more | 1–2: rows, «أولوية N/100» tag, watchlist add, glossary terms | That «أولوية» is read as list order, not confidence |
| light theme saved across a reload | 2: `data-theme` and body colour after reload | — |
| position-size calculator | 2: shares, loss at stop and R multiple for fixed inputs | Real fills (gaps, slippage and commissions are stated, not modelled) |
| offline: last saved data | 2: banner «غير متصل» + saved time, rows from the saved copy, network actually cut (service-worker requests included) | Behaviour on a real phone and OS |
| service worker update | 2: a changed `sw.js` takes over; exactly one reload; old shell cache removed | Store/home-screen install on a real device |

**Contrast:**
- WCAG AA is computed from the CSS tokens of both themes (`tests/radar_ui.cjs`).
- That is arithmetic on colours, not a screen-reader or low-vision review.
