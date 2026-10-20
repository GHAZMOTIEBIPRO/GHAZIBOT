"use strict";
// Production browser check of the public site. Writes a JSON report that
// the platform scorecards read (WEBSITE_FUNCTIONALITY). It loads pages the
// way a visitor does, records page errors, horizontal overflow at phone
// width, whether blocked sources are explained, and dollar prices shown.
const fs = require("node:fs");
const { chromium } = require("playwright");

const SITES = (process.env.SMOKE_SITES || "https://ghazibot.vercel.app,https://ghazir.vercel.app")
  .split(",").map(s => s.trim()).filter(Boolean);
const PAGES = [["home", "/"], ["chart_nvda", "/?chart=NVDA"], ["spx", "/spx/"]];
const out = process.argv[2] || "site_smoke.json";

(async () => {
  const browser = await chromium.launch();
  const pages = {};
  for (const site of SITES) {
    for (const [label, path] of PAGES) {
      const key = `${new URL(site).hostname}:${label}`;
      const page = await browser.newPage({ viewport: { width: 390, height: 900 } });
      const errors = [];
      page.on("pageerror", e => errors.push(String(e).slice(0, 200)));
      let status = null;
      try {
        const response = await page.goto(site + path, { waitUntil: "domcontentloaded", timeout: 45000 });
        status = response ? response.status() : null;
        await page.waitForTimeout(12000);
        const info = await page.evaluate(() => {
          const t = id => (document.getElementById(id)?.textContent || "").trim().slice(0, 160);
          const body = document.body.innerText;
          return {
            overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
            // Hidden tabs are part of the page too; check all text for the reason.
            blocked_reason_shown: /متوقف|LICENSE_BLOCKED|شروط/.test(document.body.textContent || ""),
            dollar_prices_shown: (body.match(/\$\s?\d{1,5}\.\d{2}/g) || []).length,
            index_panel: t("terminal-index-grid"),
            spx_status: t("status"),
          };
        });
        pages[key] = { http_status: status, errors, ...info };
      } catch (error) {
        pages[key] = { http_status: status, errors: [...errors, String(error).slice(0, 200)], overflow: null };
      }
      await page.close();
    }
  }
  await browser.close();
  const report = {
    schema: "ghazi.site_smoke.v1",
    generated_at: new Date().toISOString(),
    viewport: "390x900",
    pages,
    research_only: true,
  };
  fs.writeFileSync(out, JSON.stringify(report, null, 1));
  console.log(JSON.stringify(Object.fromEntries(Object.entries(pages).map(([k, v]) =>
    [k, { http: v.http_status, errors: (v.errors || []).length, overflow: v.overflow, blocked: v.blocked_reason_shown }]))));
})();
