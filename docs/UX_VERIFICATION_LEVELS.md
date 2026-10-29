# What the automated UX tasks prove, and what they don't

`scripts/ux_tasks.cjs` runs real Chromium against the page (phone 390×844 and desktop 1440×900, both Arabic). The task count is not usability evidence.

**Three levels are kept apart:**
1. **Shown:** the element or text is on screen.
2. **Correct:** what is shown matches the published data or the arithmetic.
3. **Understood:** a person reads it and draws the right conclusion. **No task measures level 3.** No user study has been run. "33/33 passed" means 33 scripted checks of levels 1–2, not that users understand the page.

**Cross-origin charts:**
- A chart frame that loaded proves only that TradingView's frame loaded.
- The browser does not let the page read the frame's content. What is drawn inside it, and TradingView's own "symbol not found" message, are **not verified**.
- What the page asked the frame for is checked: the interval and symbol in the frame's address.

| Task | Level checked | Not checked |
|---|---|---|
| find a stock by company name (keyboard only) | 1–2: suggestion list, Enter opens the right symbol | — |
| understand why it appears | 1: at least one reason line, 16px | 2: reason correct for the data (covered only by unit tests of the row builders); 3: understood |
| analysis availability is stated | 1: the price-analysis state sentence is present | Whether the stated state is current (the data files decide) |
| change the chart frame | 2: after pressing 1H the chart state is **ready** (timeout or failed fails the task) and the frame address asks for interval 60 (its symbol is recorded in the report). Reported NOT RUN, never passed, where TradingView is unreachable (`UX_NO_TRADINGVIEW`) | That what TradingView draws inside the frame is the right chart |
| Arabic search | 2: «انفيديا» finds NVDA | — |
| valid symbol outside S&P 500 | 2: opens with the listing from Nasdaq's file | — |
| unknown valid symbol | 2: marked unverified, no company name invented | — |
| open the original news | 1: the first news link points to its official source | That the link resolves (HEAD often blocked from the runner; status recorded, not required) |
| Federal Register notices not tied to a stock | 1: rows shown | Relevance to a stock (none is claimed) |
| week agenda (radar section) | 1–2: the «أجندة الأسبوع» card is shown with dated rows from the rebuilt data (required under `UX_LOCAL_DATA`) | That a listed date will not move (company and agency dates can change) |
| official company news | 2: each row's link stays on **that company's own** reviewed site (`data/ir_feeds.json`) | That the headline's category is right (it is read from the headline's words) |
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
