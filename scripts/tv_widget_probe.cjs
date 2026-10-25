"use strict";
// Availability probe for TradingView embed symbols, run on a GitHub runner.
// It records only whether the widget renders a symbol and which instrument
// name the widget displays (to tell a cash index from an ETF or a CFD).
// Nothing read here feeds any GHAZI analysis.
const { chromium } = require("playwright");
const fs = require("fs");

const SYMBOLS = (process.env.TV_PROBE_SYMBOLS ||
  "SP:SPX,TVC:SPX,NASDAQ:NDX,TVC:NDX,DJ:DJI,TVC:DJI,TVC:RUT,CBOE:VIX,TVC:VIX,AMEX:SPY,NASDAQ:QQQ,AMEX:IWM,AMEX:DIA," +
  "FOREXCOM:SPXUSD,FOREXCOM:NSXUSD,NASDAQ:NVDA,NASDAQ:AAPL,NYSE:BAC,NASDAQ:SOUN,NYSE:RGTI,NASDAQ:RGTI").split(",");
const BLOCK_RE = /only available on TradingView|Invalid symbol|doesn't exist|is not available|no data here/i;

async function probe(browser, symbol) {
  const page = await browser.newPage({ viewport: { width: 1000, height: 640 } });
  const cfg = { symbol, width: "100%", height: 400, locale: "en", dateRange: "1M", colorTheme: "light", isTransparent: false };
  await page.setContent(`<!doctype html><div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div>
    <script src="https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js" async>${JSON.stringify(cfg)}</script></div>`);
  await page.waitForTimeout(8000);
  let text = "";
  for (const frame of page.frames()) {
    try { text += " " + await frame.evaluate(() => (document.body ? document.body.innerText : "")); } catch { /* cross-frame */ }
  }
  await page.close();
  text = text.replace(/\s+/g, " ").trim();
  const status = BLOCK_RE.test(text) ? "NOT_AVAILABLE_IN_WIDGET" : text.length > 10 ? "RENDERED" : "EMPTY";
  // The first line of the mini overview is the instrument's display name.
  return { symbol, status, displayed: text.slice(0, 80) };
}

(async () => {
  const browser = await chromium.launch();
  const rows = [];
  for (const symbol of SYMBOLS) rows.push(await probe(browser, symbol.trim()));
  await browser.close();
  const report = { checked_at: new Date().toISOString(), widget: "mini-symbol-overview", rows };
  console.log(JSON.stringify(report, null, 1));
  const summary = process.env.GITHUB_STEP_SUMMARY;
  if (summary) {
    fs.appendFileSync(summary, "| symbol | status | displayed |\n|---|---|---|\n" +
      rows.map(r => `| ${r.symbol} | ${r.status} | ${r.displayed.replace(/\|/g, "/")} |`).join("\n") + "\n");
  }
})();
