"use strict";
// Availability probe for TradingView embed symbols, run on a GitHub runner.
// It records only whether a widget renders a symbol, which instrument name it
// displays (to tell a cash index from an ETF or a CFD) and any error text.
// Results hold only for the widget types and symbols listed in the report.
// Nothing read here feeds any GHAZI analysis.
const { chromium } = require("playwright");
const fs = require("fs");

const SYMBOLS = (process.env.TV_PROBE_SYMBOLS ||
  "SP:SPX,TVC:SPX,NASDAQ:NDX,TVC:NDX,DJ:DJI,TVC:DJI,TVC:RUT,CBOE:VIX,TVC:VIX,AMEX:SPY,NASDAQ:QQQ,AMEX:IWM,AMEX:DIA," +
  "FOREXCOM:SPXUSD,FOREXCOM:NSXUSD,NASDAQ:NVDA,NASDAQ:AAPL,NYSE:BAC,NASDAQ:SOUN,NYSE:RGTI,NASDAQ:RGTI").split(",");
const WIDGETS = (process.env.TV_PROBE_WIDGETS || "mini-symbol-overview,advanced-chart").split(",");
const BLOCK_RE = /only available on TradingView|Invalid symbol|doesn't exist|is not available|no data here/i;

function embed(widget, symbol) {
  const cfg = widget === "advanced-chart"
    ? { symbol, interval: "D", width: 980, height: 560, locale: "en", theme: "light", timezone: "America/New_York" }
    : { symbol, width: "100%", height: 400, locale: "en", dateRange: "1M", colorTheme: "light", isTransparent: false };
  return `<!doctype html><div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div>
    <script src="https://s3.tradingview.com/external-embedding/embed-widget-${widget}.js" async>${JSON.stringify(cfg)}</script></div>`;
}

async function frameText(page) {
  let text = "";
  for (const frame of page.frames()) {
    try { text += " " + await frame.evaluate(() => (document.body ? document.body.innerText : "")); } catch { /* cross-frame */ }
  }
  return text.replace(/\s+/g, " ").trim();
}

async function probe(browser, widget, symbol) {
  const page = await browser.newPage({ viewport: { width: 1000, height: 640 } });
  await page.setContent(embed(widget, symbol));
  await page.waitForTimeout(widget === "advanced-chart" ? 12000 : 8000);
  const text = await frameText(page);
  await page.close();
  const status = BLOCK_RE.test(text) ? "NOT_AVAILABLE_IN_WIDGET" : text.length > 10 ? "RENDERED" : "EMPTY";
  return { widget, symbol, status, displayed: text.slice(0, 100) };
}

(async () => {
  const browser = await chromium.launch();
  const rows = [];
  for (const widget of WIDGETS) {
    for (const symbol of SYMBOLS) {
      const row = await probe(browser, widget.trim(), symbol.trim());
      rows.push(row);
      console.log(JSON.stringify(row)); // one line per result, so partial runs still report
    }
  }
  await browser.close();
  const summary = process.env.GITHUB_STEP_SUMMARY;
  if (summary) {
    fs.appendFileSync(summary, `checked ${new Date().toISOString()}\n\n| widget | symbol | status | displayed |\n|---|---|---|---|\n` +
      rows.map(r => `| ${r.widget} | ${r.symbol} | ${r.status} | ${r.displayed.replace(/\|/g, "/")} |`).join("\n") + "\n");
  }
})();
