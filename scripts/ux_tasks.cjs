// Real user tasks on the new home page, phone and desktop, with the published
// bot-state data pinned to one commit (DATA_SHA). Files a pending change adds
// to bot-state (UX_LOCAL_DATA: name=path, comma separated) are served from the
// runner's own fresh build of them, so the tasks run on real data before merge.
//
// Each task records pass/fail and the evidence it saw; screenshots and
// ux_tasks.json go to OUT. A failed task fails the run. Nothing feeds analysis.
"use strict";
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const URL = process.env.AFTER_URL || "http://127.0.0.1:8002/";
const SHA = process.env.DATA_SHA || "";
const OUT = process.env.OUT || "ui-shots";
const LOCAL = Object.fromEntries(String(process.env.UX_LOCAL_DATA || "").split(",").filter(Boolean).map((x) => x.split("=")));
const DEVICES = {
  phone: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  desktop: { viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1 },
};
const OFFICIAL = /^https:\/\/(www\.accessdata\.fda\.gov|clinicaltrials\.gov|www\.federalregister\.gov|www\.fda\.gov|www\.sec\.gov)\//;
fs.mkdirSync(OUT, { recursive: true });
const report = { data_sha: SHA, local_files: Object.keys(LOCAL), run_at_utc: new Date().toISOString(), tasks: [] };

async function route(context) {
  await context.route(/raw\.githubusercontent\.com\/GHAZMOTIEBIPRO\/GHAZIBOT\/bot-state\//, (r) => {
    const name = r.request().url().split("/").pop();
    if (LOCAL[name] && fs.existsSync(LOCAL[name]))
      return r.fulfill({ status: 200, contentType: "application/json", body: fs.readFileSync(LOCAL[name]) });
    return SHA ? r.continue({ url: r.request().url().replace("/bot-state/", `/${SHA}/`) }) : r.continue();
  });
}
async function task(device, name, fn) {
  const t0 = Date.now();
  try {
    const evidence = await fn();
    report.tasks.push({ device, name, ok: true, ms: Date.now() - t0, evidence });
  } catch (e) {
    report.tasks.push({ device, name, ok: false, ms: Date.now() - t0, error: String(e && e.message || e).slice(0, 300) });
  }
}
const must = (cond, msg) => { if (!cond) throw new Error(msg); };
const shot = (page, file) => page.screenshot({ path: path.join(OUT, file), fullPage: false });

async function run(device) {
  const browser = await chromium.launch();
  const context = await browser.newContext({ ...DEVICES[device], locale: "ar" });
  await route(context);
  const page = await context.newPage();
  const phone = device === "phone";
  await page.goto(URL, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.querySelector("#gr-list [data-gr-symbol], #gr-list .gr-empty:not(:empty)"), null, { timeout: 20000 });
  await page.waitForTimeout(1500);
  const panelOpen = () => page.evaluate(() => document.getElementById("gr-detail").classList.contains("is-open"));
  const closeIfPhone = async () => { if (phone && await panelOpen()) { await page.keyboard.press("Escape"); await page.waitForTimeout(400); } };
  const search = async (text) => {
    await page.click("#gr-q"); await page.fill("#gr-q", ""); await page.type("#gr-q", text, { delay: 30 });
    await page.waitForTimeout(700);
    return page.$$eval("#gr-suggest li b", (els) => els.map((e) => e.textContent));
  };

  await task(device, "find a stock by symbol (keyboard only)", async () => {
    const list = await search("NVD");
    must(list[0] === "NVDA", "first suggestion " + list[0]);
    await page.keyboard.press("ArrowDown"); await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.getElementById("gr-d-symbol").textContent === "NVDA");
    return { suggestions: list.slice(0, 3) };
  });
  await task(device, "understand why it appears", async () => {
    const why = await page.$$eval("#gr-d-body section:first-child li", (els) => els.map((e) => e.textContent.trim()));
    must(why.length >= 1, "no reason listed");
    const size = await page.$eval("#gr-d-body section:first-child li", (e) => getComputedStyle(e).fontSize);
    must(size === "16px", "reason text " + size);
    return { reasons: why.slice(0, 3), font: size };
  });
  await task(device, "analysis availability is stated", async () => {
    const t = await page.$eval("#gr-d-body", (e) => e.textContent);
    must(/التحليل السعري/.test(t) && /ضمن المصادر التي اختبرناها/.test(t), "price analysis state missing");
    const fresh = await page.$eval("#gr-facts", (e) => e.textContent);
    return { facts: fresh.replace(/\s+/g, " ").slice(0, 200) };
  });
  await task(device, "change the chart frame", async () => {
    await page.click('[data-gr-chart] .gr-chart-bar button[data-interval="60"]');
    const pressed = await page.$eval('[data-gr-chart] .gr-chart-bar button[data-interval="60"]', (b) => b.getAttribute("aria-pressed"));
    must(pressed === "true", "frame button not pressed");
    await page.waitForFunction(() => document.querySelector("[data-gr-chart]").dataset.state !== "loading", null, { timeout: 20000 }).catch(() => {});
    const state = await page.$eval("[data-gr-chart]", (b) => b.dataset.state);
    must(["ready", "timeout", "failed"].includes(state), "chart state " + state);
    await shot(page, `ux-${device}-chart-1h.png`);
    return { chart_state: state };
  });
  await closeIfPhone();
  await task(device, "Arabic search", async () => {
    const list = await search("انفيديا");
    must(list[0] === "NVDA", "Arabic search gave " + list[0]);
    const sector = await search("الرعاية");
    must(sector.length > 0, "Arabic sector search empty");
    await page.fill("#gr-q", ""); await page.keyboard.press("Escape");
    return { name: list[0], sector_hits: sector.slice(0, 4) };
  });
  await task(device, "a valid symbol outside S&P 500 opens with verified listing", async () => {
    await search("SOUN"); await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.getElementById("gr-d-symbol").textContent === "SOUN");
    await page.waitForFunction(() => /مدرج في ناسداك/.test(document.getElementById("gr-d-body").textContent), null, { timeout: 15000 });
    const name = await page.$eval("#gr-d-name", (e) => e.textContent);
    must(/SoundHound/.test(name), "name " + name);
    await shot(page, `ux-${device}-soun.png`);
    return { name };
  });
  await closeIfPhone();
  await task(device, "an unknown valid symbol is marked unverified, not named", async () => {
    await search("QXQZ"); await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.getElementById("gr-d-symbol").textContent === "QXQZ");
    const t = await page.$eval("#gr-d-body section:first-child", (e) => e.textContent);
    const name = await page.$eval("#gr-d-name", (e) => e.textContent);
    must(/لم نتحقق/.test(t) && name === "", "unverified wording or invented name");
    return { reason: t.trim().slice(0, 160) };
  });
  await closeIfPhone();
  await task(device, "open the original news", async () => {
    await page.click("#gr-tab-news"); await page.waitForTimeout(500);
    const links = await page.$$eval("#gr-list .gr-row-link", (as) => as.slice(0, 20).map((a) => ({ href: a.href, target: a.target })));
    must(links.length > 0, "no source links");
    must(links.every((l) => OFFICIAL.test(l.href) && l.target === "_blank"), "non-official or same-tab link");
    const first = links[0].href;
    const status = await page.request.head(first, { timeout: 15000 }).then((r) => r.status()).catch((e) => "error " + e.message.slice(0, 60));
    const dist = await page.$eval(".gr-dist summary", (e) => e.textContent).catch(() => "");
    must(/حسب المصدر/.test(dist), "news distribution missing");
    await page.click(".gr-dist summary");
    await shot(page, `ux-${device}-news.png`);
    return { first_link: first, http_status: status, distribution: dist };
  });
  await task(device, "Federal Register notices not tied to a stock", async () => {
    if (phone) await page.selectOption("#gr-list-tools select", "general");
    else await page.click('#gr-list-tools button:has-text("غير مرتبطة")');
    await page.waitForTimeout(500);
    const rows = await page.$$eval("#gr-list .gr-row", (els) => els.length);
    must(rows > 0, "no general notices");
    await shot(page, `ux-${device}-general.png`);
    return { rows };
  });
  await task(device, "catalysts tab and Nasdaq listing flags", async () => {
    await page.click("#gr-tab-small"); await page.waitForTimeout(800);
    const title = await page.$eval("#gr-list-title", (e) => e.textContent);
    must(title === "أسهم ذات محفزات", "title " + title);
    const catalysts = await page.$$eval("#gr-list [data-gr-symbol]", (els) => els.length);
    await shot(page, `ux-${device}-catalysts.png`);
    await page.selectOption("#gr-list-tools select", "flags");
    await page.waitForFunction(() => document.querySelectorAll("#gr-list [data-gr-symbol]").length > 0, null, { timeout: 15000 });
    const flags = await page.$$eval("#gr-list [data-gr-symbol]", (els) => els.length);
    const sample = await page.$eval("#gr-list .gr-why", (e) => e.textContent);
    must(/تنبيه ناسداك/.test(sample), "flag wording " + sample);
    await shot(page, `ux-${device}-flags.png`);
    await page.selectOption("#gr-list-tools select", "catalysts");
    return { catalyst_rows: catalysts, flag_rows: flags, sample };
  });
  await task(device, "a Federal Register risk event on the stock page", async () => {
    await search("BA"); await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.getElementById("gr-d-symbol").textContent === "BA");
    const news = await page.$eval("#gr-d-body", (e) => e.textContent);
    must(/صلاحية طيران/.test(news), "no FAA directive on BA");
    const href = await page.$eval('#gr-d-body a[href*="federalregister.gov"]', (a) => a.href);
    await shot(page, `ux-${device}-ba.png`);
    return { link: href };
  });
  await closeIfPhone();
  if (phone) {
    await task(device, "phone back button closes the stock and keeps the list position", async () => {
      await page.click("#gr-tab-leaders"); await page.waitForTimeout(500);
      await page.evaluate(() => window.scrollTo(0, 700)); await page.waitForTimeout(300);
      const before = await page.evaluate(() => Math.round(window.scrollY));
      const row = await page.$$("#gr-list .gr-row-open");
      must(row.length > 6, "too few rows");
      await row[6].click(); await page.waitForTimeout(500);
      must(await panelOpen(), "panel did not open");
      await page.goBack(); await page.waitForTimeout(600);
      must(!(await panelOpen()), "back did not close the panel");
      const after = await page.evaluate(() => Math.round(window.scrollY));
      must(Math.abs(after - before) <= 4, `list moved ${before} -> ${after}`);
      const focused = await page.evaluate(() => document.activeElement && document.activeElement.className);
      return { scroll_before: before, scroll_after: after, focus: focused };
    });
    await task(device, "Escape closes the stock panel", async () => {
      const row = await page.$$("#gr-list .gr-row-open");
      await row[2].click(); await page.waitForTimeout(400);
      await page.keyboard.press("Escape"); await page.waitForTimeout(400);
      must(!(await panelOpen()), "still open");
      return { closed: true };
    });
    await task(device, "each tab keeps its scroll position", async () => {
      await page.evaluate(() => window.scrollTo(0, 500)); await page.waitForTimeout(200);
      await page.click("#gr-tab-news"); await page.waitForTimeout(300);
      await page.click("#gr-tab-leaders"); await page.waitForTimeout(300);
      const y = await page.evaluate(() => Math.round(window.scrollY));
      must(Math.abs(y - 500) <= 4, "leaders scroll " + y);
      return { restored: y };
    });
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.click("#gr-tab-leaders"); await page.waitForTimeout(400);
  await shot(page, `ux-${device}-leaders.png`);
  await browser.close();
}

(async () => {
  for (const d of Object.keys(DEVICES)) await run(d);
  fs.writeFileSync(path.join(OUT, "ux_tasks.json"), JSON.stringify(report, null, 1));
  for (const t of report.tasks) console.log(`${t.ok ? "PASS" : "FAIL"} ${t.device} | ${t.name} | ${t.ok ? JSON.stringify(t.evidence).slice(0, 220) : t.error}`);
  const failed = report.tasks.filter((t) => !t.ok).length;
  console.log(`${report.tasks.length - failed}/${report.tasks.length} tasks passed`);
  process.exit(failed ? 1 : 0);
})();
