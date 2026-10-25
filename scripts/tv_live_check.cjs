"use strict";
// Visual check of the external charts on the live site: for each section, the
// symbol and frame our page asked for, what TradingView actually shows inside
// the chart (its title line, or an error message), and whether a frame loaded.
// Quality check only; nothing read here feeds GHAZI analysis.
const { chromium } = require("playwright");
const fs = require("fs");

const SITE = process.env.LIVE_SITE || "https://ghazibot.vercel.app";
const BLOCK_RE = /only available on TradingView|Invalid symbol|doesn't exist|is not available|no data here/i;
const SECTIONS = [["indices", "SPX"], ["large", "NVDA"], ["small", "SOUN"]];

(async () => {
  const browser = await chromium.launch();
  const rows = [];
  for (const width of [390, 1366]) {
    for (const [tab, expect] of SECTIONS) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      const errors = [];
      page.on("pageerror", e => errors.push(String(e).slice(0, 160)));
      await page.goto(SITE + "/", { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForTimeout(3000);
      await page.evaluate(t => document.querySelector(`[data-terminal-tab="${t}"]`)?.click(), tab);
      const view = `#terminal-panel-${tab} [data-tv-chart-view]`;
      await page.evaluate(sel => document.querySelector(sel)?.scrollIntoView(), view);
      await page.waitForTimeout(14000);
      const ours = await page.evaluate(sel => {
        const box = document.querySelector(sel);
        const slot = box?.querySelector(".ghazi-tv-slot--chart");
        return {mounted: slot?.dataset.mounted || null, caption: (box?.querySelector(".terminal-footnote")?.textContent || "").slice(0, 140),
                frames: slot ? slot.querySelectorAll("iframe").length : 0};
      }, view);
      let inside = "";
      for (const frame of page.frames()) {
        if (!/tradingview/.test(frame.url())) continue;
        try { inside += " " + await frame.evaluate(() => document.body ? document.body.innerText : ""); } catch { /* ignore */ }
      }
      inside = inside.replace(/\s+/g, " ").trim();
      const row = {width, section: tab, expected_symbol_contains: expect, ...ours,
                   widget_error: BLOCK_RE.test(inside) ? inside.match(BLOCK_RE)[0] : null,
                   widget_text_start: inside.slice(0, 120), page_errors: errors.length};
      rows.push(row);
      console.log(JSON.stringify(row));
      await page.close();
    }
  }
  await browser.close();
  if (process.env.GITHUB_STEP_SUMMARY) {
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, "| width | section | mounted | frames | widget error | widget text |\n|---|---|---|---|---|---|\n" +
      rows.map(r => `| ${r.width} | ${r.section} | ${r.mounted} | ${r.frames} | ${r.widget_error || ""} | ${r.widget_text_start.replace(/\|/g, "/")} |`).join("\n") + "\n");
  }
})();
