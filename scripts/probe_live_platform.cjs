"use strict";
// Log-only check of the production pages: does the live site serve this build's «حالة المنصة»
// card and the data-state line? Nothing is stored or sent.
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch();
  const out = {};
  for (const host of ["https://ghazibot.vercel.app/", "https://ghazir.vercel.app/"]) {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const row = { host };
    try {
      const res = await page.goto(host, { waitUntil: "domcontentloaded", timeout: 45000 });
      row.http = res ? res.status() : null;
      row.script = await page.$eval('script[src*="radar.js"]', (e) => e.getAttribute("src")).catch(() => null);
      await page.waitForFunction(() => document.querySelectorAll("#gr-facts .gr-fact").length > 1, null, { timeout: 30000 }).catch(() => {});
      row.data_fact = await page.$$eval("#gr-facts .gr-fact", (els) => (els.map((e) => e.textContent).find((t) => /حالة البيانات/.test(t)) || "").slice(0, 220));
      await page.click('[data-gr-section="more"]');
      await page.waitForSelector(".gr-platform .gr-state", { timeout: 15000 });
      row.blocks = await page.$$eval(".gr-platform .gr-state", (els) => els.map((e) => ({ state: e.dataset.state,
        title: e.querySelector("h3").textContent.trim(), line: e.querySelector("p").textContent.trim().slice(0, 200) })));
      row.source_rows = await page.$$eval(".gr-platform li[data-state]", (els) => els.length);
    } catch (err) {
      row.error = String(err.message || err).slice(0, 200);
    }
    out[host] = row;
    await page.close();
  }
  console.log("LIVE " + JSON.stringify(out));
  // Signal page route (/options/signal/{id} -> /signal) on both hosts: served, scripts load,
  // no page errors, and an honest status line for an id that is not in the ledger.
  const sig = {};
  for (const host of ["https://ghazibot.vercel.app", "https://ghazir.vercel.app"]) {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
    const row = { host };
    try {
      const res = await page.goto(host + "/options/signal/0123456789abcdef", { waitUntil: "domcontentloaded", timeout: 45000 });
      row.http = res ? res.status() : null;
      row.title = await page.title();
      await page.waitForTimeout(8000);
      row.status = (await page.textContent("#status").catch(() => "") || "").trim().slice(0, 200);
      row.chart_lib = await page.evaluate(() => typeof LightweightCharts !== "undefined");
      row.ledger_http = await page.evaluate(async () => {
        try { return (await fetch("https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/signal_ledger.json", { cache: "no-store" })).status; }
        catch (e) { return "fetch_error"; }
      });
    } catch (err) {
      row.error = String(err.message || err).slice(0, 200);
    }
    row.page_errors = errors;
    sig[host] = row;
    await page.close();
  }
  console.log("SIGNAL_PAGE " + JSON.stringify(sig));
  await browser.close();
})();
