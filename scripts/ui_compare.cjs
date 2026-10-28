// Before/after comparison of the public page under identical conditions.
//
// Both copies of the site are served locally and every bot-state data request
// is pinned to one commit (DATA_SHA), so the two pages read the same real
// data. Same viewports, same waits. Writes screenshots, one phone video of the
// new page and metrics.json to OUT. Nothing here feeds analysis.
"use strict";
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const BEFORE = process.env.BEFORE_URL || "http://127.0.0.1:8001/";
const AFTER = process.env.AFTER_URL || "http://127.0.0.1:8002/";
const SHA = process.env.DATA_SHA || "";
const OUT = process.env.OUT || "ui-shots";
const WAIT = Number(process.env.UI_WAIT_MS || 7000);
const VIEWPORTS = {
  phone: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  desktop: { viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1 },
};

fs.mkdirSync(OUT, { recursive: true });
const metrics = { data_sha: SHA, taken_at_utc: new Date().toISOString(), pages: {} };

async function pin(context) {
  if (!SHA) return;
  await context.route(/raw\.githubusercontent\.com\/GHAZMOTIEBIPRO\/GHAZIBOT\/bot-state\//, (route) =>
    route.continue({ url: route.request().url().replace("/bot-state/", `/${SHA}/`) }));
}

// Runs inside the page: text size, contrast, repeated "unavailable", English
// operational labels, and how far down the first visible chart frame sits.
function measure() {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && Number(s.opacity) > 0;
  };
  const rgb = (c) => (c.match(/[\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const background = (el) => {
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const c = rgb(getComputedStyle(node).backgroundColor);
      if (c.length >= 3 && (c.length < 4 || c[3] > 0.6)) return c.slice(0, 3);
    }
    return [255, 255, 255];
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const sizes = [];
  let unavailable = 0, english = 0, lowContrast = 0, nodes = 0;
  const seen = new Set();
  while (walker.nextNode()) {
    const text = walker.currentNode.nodeValue.trim();
    const el = walker.currentNode.parentElement;
    if (!text || !el || !visible(el) || el.closest("script,style,noscript")) continue;
    nodes++;
    const style = getComputedStyle(el);
    sizes.push(parseFloat(style.fontSize));
    if (/غير متاح|غير متوفر|UNAVAILABLE|unavailable/.test(text)) unavailable++;
    // Interface labels only: official product or study names inside data rows are content, not labels.
    if (/^[A-Z][A-Z0-9 ·&\/+\-:.,()]{7,}$/.test(text) && !el.closest(".gr-row, .gr-d-list")) english++;
    if (!seen.has(el)) {
      seen.add(el);
      const fg = rgb(style.color).slice(0, 3);
      const a = lum(fg), b = lum(background(el));
      const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      const large = parseFloat(style.fontSize) >= 24 || (parseFloat(style.fontSize) >= 18.66 && Number(style.fontWeight) >= 700);
      if (ratio < (large ? 3 : 4.5)) lowContrast++;
    }
  }
  sizes.sort((x, y) => x - y);
  const at = (p) => sizes.length ? sizes[Math.floor((sizes.length - 1) * p)] : null;
  // The stock chart, not the price tape or other widgets: the new page's chart box, or the old page's chart views.
  const frame = [...document.querySelectorAll("[data-gr-chart] iframe, [data-tv-chart-view] iframe, #terminal-tv-chart-slot iframe")]
    .find((f) => /tradingview/i.test(f.src || "") && visible(f));
  return {
    page_height_px: document.documentElement.scrollHeight,
    viewport_height_px: innerHeight,
    screens_to_scroll: +(document.documentElement.scrollHeight / innerHeight).toFixed(1),
    visible_text_nodes: nodes,
    font_px_min: at(0), font_px_p10: at(0.1), font_px_median: at(0.5),
    unavailable_mentions: unavailable,
    english_ops_labels: english,
    low_contrast_text_elements: lowContrast,
    // Where the chart is on screen right after the stock opens, and whether it is
    // visible without scrolling (a fixed detail sheet does not move with the page).
    chart_top_on_screen_px: frame ? Math.round(frame.getBoundingClientRect().top) : null,
    chart_visible_without_scrolling: frame ? frame.getBoundingClientRect().top >= 0 && frame.getBoundingClientRect().top < innerHeight - 80 : null,
    first_chart_frame_y_px: frame ? Math.round(frame.getBoundingClientRect().top + scrollY) : null,
    horizontal_overflow: document.documentElement.scrollWidth > innerWidth + 1,
  };
}

async function shoot(page, name, screens = 1) {
  for (let i = 0; i < screens; i++) {
    await page.evaluate((y) => window.scrollTo(0, y), i * page.viewportSize().height);
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(OUT, `${name}${screens > 1 ? `-${i + 1}` : ""}.png`) });
  }
  await page.evaluate(() => window.scrollTo(0, 0));
}

async function open(browser, kind, video) {
  const context = await browser.newContext({
    ...VIEWPORTS[kind], locale: "ar", timezoneId: "Asia/Riyadh",
    serviceWorkers: "block",   // a worker's own fetches would bypass the pinned-data route
    ...(video ? { recordVideo: { dir: OUT, size: VIEWPORTS[kind].viewport } } : {}),
  });
  await pin(context);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e.message || e).slice(0, 160)));
  return { context, page, errors };
}

async function before(browser, kind) {
  const { context, page, errors } = await open(browser, kind);
  await page.goto(BEFORE, { waitUntil: "load" });
  await page.waitForTimeout(WAIT);
  metrics.pages[`before-${kind}-home`] = { ...(await page.evaluate(measure)), page_errors: errors.length };
  await shoot(page, `before-${kind}-home`, 3);
  // The old home page's way to a stock: its NVDA shortcut.
  await page.goto(`${BEFORE}?chart=NVDA`, { waitUntil: "load" });
  await page.waitForTimeout(WAIT);
  metrics.pages[`before-${kind}-stock`] = { ...(await page.evaluate(measure)), page_errors: errors.length };
  await page.screenshot({ path: path.join(OUT, `before-${kind}-stock.png`) });
  await context.close();
}

async function after(browser, kind) {
  const { context, page, errors } = await open(browser, kind, kind === "phone");
  await page.goto(AFTER, { waitUntil: "load" });
  await page.waitForTimeout(WAIT);
  metrics.pages[`after-${kind}-home`] = { ...(await page.evaluate(measure)), page_errors: errors.length };
  await shoot(page, `after-${kind}-home`, 2);
  for (const tab of ["indices", "leaders", "small", "options", "news"]) {
    const button = page.locator(`[data-gr-tab="${tab}"], [data-gr-section="${tab}"]`).first();
    if (!(await button.count())) continue;
    await button.click();
    await page.waitForTimeout(1200);
    metrics.pages[`after-${kind}-tab-${tab}`] = await page.evaluate(measure);
    await page.screenshot({ path: path.join(OUT, `after-${kind}-tab-${tab}.png`) });
  }
  // Same stock as the "before" flow: NVDA from the leaders tab.
  const market = page.locator('[data-gr-section="market"]').first();   // market sub-tabs are hidden in other sections
  if (await market.count()) await market.click();
  const leaders = page.locator('[data-gr-tab="leaders"]').first();
  if (await leaders.count()) {
    await leaders.click();
    await page.waitForTimeout(800);
  }
  const row = page.locator('[data-gr-symbol="NVDA"]').first();
  if (await row.count()) {
    await row.click();
    await page.waitForTimeout(WAIT);
    const chart = await page.evaluate(() => {
      const box = document.querySelector("[data-gr-chart]");
      return box ? { state: box.getAttribute("data-state"), symbol: box.getAttribute("data-symbol") } : null;
    });
    metrics.pages[`after-${kind}-stock`] = { ...(await page.evaluate(measure)), chart, page_errors: errors.length };
    await page.screenshot({ path: path.join(OUT, `after-${kind}-stock.png`) });
    if (kind === "phone") {
      await page.evaluate(() => window.scrollTo(0, 99999));
      await page.waitForTimeout(600);
      await page.screenshot({ path: path.join(OUT, `after-${kind}-stock-2.png`) });
      await page.goBack();
      await page.waitForTimeout(800);
      await page.locator('[data-gr-tab="news"], [data-gr-section="news"]').first().click();
      await page.waitForTimeout(1000);
      await page.mouse.wheel(0, 900);
      await page.waitForTimeout(1200);
    }
  }
  metrics.pages[`after-${kind}-home`].page_errors = errors.length;
  const video = page.video();
  await context.close();
  if (video) fs.renameSync(await video.path(), path.join(OUT, `after-${kind}-flow.webm`));
}

(async () => {
  const browser = await chromium.launch();
  for (const kind of Object.keys(VIEWPORTS)) {
    await before(browser, kind);
    await after(browser, kind);
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, "metrics.json"), JSON.stringify(metrics, null, 1));
  console.log(JSON.stringify(metrics, null, 1));
})().catch((e) => { console.error(e); process.exit(1); });
