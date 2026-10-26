"use strict";
// Visual check of the external chart on the live site: for one symbol per
// section, the symbol our page asked for, the chart state our page recorded
// (loading / ready / timeout / failed / unavailable), what TradingView
// actually shows inside the chart (its title line, or an error message) and
// whether a frame loaded. Playwright can read the frame; the page itself
// cannot (cross-origin), which is why it records only load state.
// Quality check only; nothing read here feeds GHAZI analysis.
const { chromium } = require("playwright");
const fs = require("fs");

const SITE = process.env.LIVE_SITE || "https://ghazibot.vercel.app";
const BLOCK_RE = /only available on TradingView|Invalid symbol|doesn't exist|is not available|no data here/i;
const SECTIONS = [["indices", "SPY"], ["leaders", "NVDA"], ["small", "SOUN"]];

(async () => {
  const browser = await chromium.launch();
  const rows = [];
  for (const width of [390, 1366]) {
    for (const [tab, symbol] of SECTIONS) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const errors = [];
      page.on("pageerror", e => errors.push(String(e).slice(0, 160)));
      await page.goto(`${SITE}/?tab=${tab}&s=${symbol}`, { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForTimeout(16000);
      const ours = await page.evaluate(() => {
        const box = document.querySelector("[data-gr-chart]");
        return { requested: box?.dataset.symbol || null, state: box?.dataset.state || null,
                 frames: box ? box.querySelectorAll("iframe").length : 0,
                 caption: (box?.querySelector(".gr-chart-note")?.textContent || "").slice(0, 140),
                 detail_open: document.getElementById("gr-detail")?.classList.contains("is-open") || false };
      });
      let inside = "";
      for (const frame of page.frames()) {
        if (!/tradingview/.test(frame.url()) || /ticker-tape/.test(frame.url())) continue;
        try { inside += " " + await frame.evaluate(() => document.body ? document.body.innerText : ""); } catch { /* ignore */ }
      }
      inside = inside.replace(/\s+/g, " ").trim();
      const row = { width, section: tab, symbol, ...ours,
                    widget_error: BLOCK_RE.test(inside) ? inside.match(BLOCK_RE)[0] : null,
                    widget_text_start: inside.slice(0, 120), page_errors: errors.length };
      rows.push(row);
      console.log(JSON.stringify(row));
      await page.close();
    }
  }
  await browser.close();
  if (process.env.GITHUB_STEP_SUMMARY) {
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, "| width | section | symbol | state | frames | widget error | widget text |\n|---|---|---|---|---|---|---|\n" +
      rows.map(r => `| ${r.width} | ${r.section} | ${r.symbol} | ${r.state} | ${r.frames} | ${r.widget_error || ""} | ${r.widget_text_start.replace(/\|/g, "/")} |`).join("\n") + "\n");
  }
})();
