"use strict";
// Production browser check of the public site. Writes a JSON report that
// the platform scorecards read (WEBSITE_FUNCTIONALITY). It loads pages the
// way a visitor does, records page errors, horizontal overflow at phone
// width, whether blocked sources are explained, and dollar prices shown.
const fs = require("node:fs");
const { chromium } = require("playwright");

const SITES = (process.env.SMOKE_SITES || "https://ghazibot.vercel.app,https://ghazir.vercel.app")
  .split(",").map(s => s.trim()).filter(Boolean);
const PAGES = [["home", "/"], ["chart_nvda", "/?chart=NVDA"], ["news", "/?tab=news"], ["classic", "/classic.html"],
               ["spx", "/spx/"]];
const out = process.argv[2] || "site_smoke.json";
// Does production serve this checkout (main)? Every versioned local script (`src="...?v=..."`) of the page's
// HTML file must be in the served page, and the service worker must carry the same VERSION.
const PAGE_FILES = { home: "public/index.html", chart_nvda: "public/index.html", news: "public/index.html",
                     classic: "public/classic.html", spx: "public/spx/index.html" };
const expectedScripts = file => {
  try {
    return [...fs.readFileSync(file, "utf8").matchAll(/<script[^>]*\ssrc="([^"]*\?v=[^"]*)"/g)].map(m => m[1]).sort();
  } catch { return null; }
};
const swVersion = text => (/VERSION\s*=\s*["']([^"']+)/.exec(text || "") || [])[1] || null;
const readOrNull = file => { try { return fs.readFileSync(file, "utf8"); } catch { return null; } };

(async () => {
  const browser = await chromium.launch();
  const pages = {};
  const sites = {};
  const expectedSw = swVersion(readOrNull("public/sw.js"));
  for (const site of SITES) {
    const ctx = await browser.newContext();
    let servedSw = null;
    try {
      const response = await ctx.request.get(`${site}/sw.js`, { timeout: 20000 });
      servedSw = response.ok() ? swVersion(await response.text()) : null;
    } catch { servedSw = null; }
    await ctx.close();
    sites[new URL(site).hostname] = { sw_served: servedSw, sw_expected: expectedSw,
                                      sw_match: expectedSw ? servedSw === expectedSw : null };
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
            // Our own page text only: innerText never includes iframe content, so
            // prices inside a permitted external widget (TradingView) are not
            // counted here; a non-zero value means GHAZI itself printed a price.
            own_dom_dollar_prices: (body.match(/\$\s?\d{1,5}\.\d{2}/g) || []).length,
            external_widget_frames: [...document.querySelectorAll("iframe")]
              .filter(f => /tradingview/.test(f.src || "")).length,
            index_panel: t("terminal-index-grid"),
            spx_status: t("status"),
            // New home page: rows shown, the chart state it recorded, and the smallest text.
            list_rows: document.querySelectorAll("#gr-list .gr-row").length,
            chart_state: document.querySelector("[data-gr-chart]")?.dataset.state || null,
            chart_symbol: document.querySelector("[data-gr-chart]")?.dataset.symbol || null,
            // Home summary: which cards the visitor sees (labels only, no values).
            fact_cards: [...document.querySelectorAll("#gr-facts .gr-fact-label")]
              .map(e => (e.textContent || "").trim().slice(0, 60)),
            radar_js: document.querySelector("script[src*='radar.js?v=']")?.getAttribute("src") || null,
            scripts: [...document.querySelectorAll("script[src*='?v=']")].map(s => s.getAttribute("src")).sort(),
          };
        });
        const expected = expectedScripts(PAGE_FILES[label]);
        info.scripts_missing = expected ? expected.filter(src => !info.scripts.includes(src)) : null;
        info.version_match = expected ? info.scripts_missing.length === 0 : null;
        // TradingView widgets load lazily: open the section, scroll to it, then
        // count the frames TradingView injected (their content stays inside them).
        // New page: the price tape on home, the stock chart on a ?chart= link.
        // The old page (classic.html) keeps its own lazy widgets.
        const tvTarget = label === "chart_nvda" ? [null, "[data-gr-chart]"] : label === "home" ? [null, "#gr-tape"]
          : label === "classic" ? ["indices", "#tv-index-ta"] : null;
        if (tvTarget) {
          await page.evaluate(([tab, sel]) => {
            if (tab) document.querySelector(`[data-terminal-tab="${tab}"]`)?.click();
            document.querySelector(sel)?.scrollIntoView();
          }, tvTarget);
          await page.waitForTimeout(8000);
          info.tradingview_frames = await page.evaluate(sel =>
            document.querySelector(sel)?.querySelectorAll("iframe").length || 0, tvTarget[1]);
          if (label === "chart_nvda") info.chart_state = await page.evaluate(() =>
            document.querySelector("[data-gr-chart]")?.dataset.state || null);
        }
        pages[key] = { http_status: status, errors, ...info };
      } catch (error) {
        pages[key] = { http_status: status, errors: [...errors, String(error).slice(0, 200)], overflow: null };
      }
      await page.close();
    }
  }
  await browser.close();
  const checks = [...Object.values(pages).map(p => p.version_match), ...Object.values(sites).map(s => s.sw_match)];
  const report = {
    schema: "ghazi.site_smoke.v1",
    generated_at: new Date().toISOString(),
    viewport: "390x900",
    checked_commit: process.env.GITHUB_SHA || null,
    // true only when every page serves this checkout's scripts and every site its service-worker version
    production_matches_checkout: checks.length && checks.every(v => v !== null) ? checks.every(Boolean) : null,
    sites,
    pages,
    research_only: true,
  };
  fs.writeFileSync(out, JSON.stringify(report, null, 1));
  console.log(JSON.stringify(Object.fromEntries(Object.entries(pages).map(([k, v]) =>
    [k, { http: v.http_status, errors: (v.errors || []).length, overflow: v.overflow, blocked: v.blocked_reason_shown,
          tv: v.tradingview_frames, versions: v.version_match }]))));
  console.log(JSON.stringify({ production_matches_checkout: report.production_matches_checkout, sites }));
})();
