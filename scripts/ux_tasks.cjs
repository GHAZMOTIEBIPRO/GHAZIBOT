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
// context.setOffline/route do not reach service-worker requests unless this is set before launch.
process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS = "1";
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
  const context = await browser.newContext({ ...DEVICES[device], locale: "ar", serviceWorkers: "block" });
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

  await task(device, "find a stock by company name (keyboard only)", async () => {
    // By name: with the Nasdaq directory loaded, a partial symbol such as "NVD" is itself a listed symbol.
    const list = await search("nvidia");
    must(list[0] === "NVDA", "first suggestion " + list[0]);
    const exact = await search("NVD");
    must(exact[0] === "NVD", "an exact listed symbol ranks first: " + exact[0]);
    await page.fill("#gr-q", ""); await search("nvidia");
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
    await page.waitForTimeout(500);
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
    await page.click('[data-gr-section="news"]'); await page.waitForTimeout(500);
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
    await page.click('[data-gr-section="market"]'); await page.click("#gr-tab-small"); await page.waitForTimeout(800);
    const title = await page.$eval("#gr-list-title", (e) => e.textContent);
    must(title === "أسهم ذات محفزات", "title " + title);
    const catalysts = await page.$$eval("#gr-list [data-gr-symbol]", (els) => els.length);
    await shot(page, `ux-${device}-catalysts.png`);
    await page.selectOption("#gr-list-tools select", "flags");
    await page.waitForFunction(() => document.querySelectorAll("#gr-list [data-gr-symbol]").length > 0, null, { timeout: 15000 });
    const flags = await page.$$eval("#gr-list [data-gr-symbol]", (els) => els.length);
    const sample = await page.$eval("#gr-list .gr-why", (e) => e.textContent);
    must(/تنبيه ناسداك/.test(sample), "flag wording " + sample);
    // The shown count is traceable to the file, and a flag is not presented as a delisting decision.
    const note = await page.$eval("#gr-list-note", (e) => e.textContent);
    must(note.includes(`المعروض ${flags.toLocaleString("en-US")} سهمًا`) && /ليس قرار شطب/.test(note), "flag note " + note);
    await page.click(".gr-note-more summary");
    const codes = await page.$$eval(".gr-note-more dt", (els) => els.length);
    must(codes >= 3, "code meanings " + codes);
    await shot(page, `ux-${device}-flags.png`);
    await page.selectOption("#gr-list-tools select", "catalysts");
    return { catalyst_rows: catalysts, flag_rows: flags, sample, note: note.slice(0, 220), code_meanings: codes };
  });
  await task(device, "a Federal Register risk event on the stock page", async () => {
    await search("BA"); await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.getElementById("gr-d-symbol").textContent === "BA");
    const news = await page.$eval("#gr-d-body", (e) => e.textContent);
    must(/صلاحية طيران/.test(news), "no FAA directive on BA");
    const href = await page.$eval('#gr-d-body a[href*="federalregister.gov"]', (a) => a.href);
    await page.waitForTimeout(500);   // the phone panel slides in; capture after it settles
    await shot(page, `ux-${device}-ba.png`);
    return { link: href };
  });
  await closeIfPhone();
  if (phone) {
    await task(device, "phone back button closes the stock and keeps the list position", async () => {
      await page.click('[data-gr-section="market"]'); await page.click("#gr-tab-leaders"); await page.waitForTimeout(500);
      await page.evaluate(() => window.scrollTo(0, 700)); await page.waitForTimeout(300);
      // What the user sees: the opened row is where it was on screen (page scroll may shift if content above grew).
      const before = await page.evaluate(() => Math.round(window.scrollY));
      const row = await page.$$("#gr-list .gr-row-open");
      must(row.length > 6, "too few rows");
      const sym = await row[6].evaluate((b) => b.closest("[data-gr-symbol]").dataset.grSymbol);
      const topOf = () => page.evaluate((s) => Math.round(document.querySelector(`#gr-list [data-gr-symbol="${s}"]`).getBoundingClientRect().top), sym);
      const rowBefore = await topOf();
      await row[6].click(); await page.waitForTimeout(500);
      must(await panelOpen(), "panel did not open");
      // Late data grows the content above the list while the stock is open (as on the runner: +21px).
      await page.evaluate(() => { const d = document.createElement("div"); d.id = "ux-shift"; d.style.height = "50px"; document.getElementById("gr-list").before(d); });
      await page.goBack(); await page.waitForTimeout(600);
      must(!(await panelOpen()), "back did not close the panel");
      const after = await page.evaluate(() => Math.round(window.scrollY));
      const rowAfter = await topOf();
      await page.evaluate(() => document.getElementById("ux-shift").remove());
      must(Math.abs(rowAfter - rowBefore) <= 4, `row ${sym} moved on screen ${rowBefore} -> ${rowAfter} (scroll ${before} -> ${after})`);
      const focused = await page.evaluate(() => document.activeElement && document.activeElement.className);
      return { row: sym, row_top_before: rowBefore, row_top_after: rowAfter, scroll_before: before, scroll_after: after, focus: focused };
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
      await page.click('[data-gr-section="news"]'); await page.waitForTimeout(300);
      await page.click('[data-gr-section="market"]'); await page.click("#gr-tab-leaders"); await page.waitForTimeout(300);
      const y = await page.evaluate(() => Math.round(window.scrollY));
      must(Math.abs(y - 500) <= 4, "leaders scroll " + y);
      return { restored: y };
    });
  }
  await task(device, "app sections: radar, watchlist, more", async () => {
    await page.click('[data-gr-section="radar"]'); await page.waitForTimeout(500);
    const radar = await page.$$eval("#gr-list [data-gr-symbol]", (els) => els.length);
    const tag = await page.$eval("#gr-list .gr-tag", (e) => e.textContent).catch(() => "");
    must(radar > 0 && /أولوية/.test(tag), "radar rows " + radar);
    await shot(page, `ux-${device}-radar.png`);
    await page.click('[data-gr-section="watch"]'); await page.waitForTimeout(300);
    const before = await page.$$eval("#gr-list [data-gr-symbol]", (els) => els.length);
    await search("NVDA"); await page.keyboard.press("Enter");
    await page.waitForFunction(() => document.getElementById("gr-d-symbol").textContent === "NVDA");
    if ((await page.getAttribute("#gr-d-watch", "aria-pressed")) !== "true") await page.click("#gr-d-watch");
    await closeIfPhone();
    await page.click('[data-gr-section="watch"]'); await page.waitForTimeout(300);
    const after = await page.$$eval("#gr-list [data-gr-symbol]", (els) => els.map((e) => e.dataset.grSymbol));
    const badge = await page.$eval("#gr-watch-count", (e) => e.textContent);
    must(after.includes("NVDA") && badge !== "", "watchlist " + after.join(","));
    await page.click('[data-gr-section="more"]'); await page.waitForTimeout(300);
    const terms = await page.$$eval(".gr-glossary dt", (els) => els.length);
    must(terms >= 8, "glossary " + terms);
    return { radar_rows: radar, first_tag: tag, watch_before: before, watch_after: after, glossary_terms: terms };
  });
  await task(device, "light theme is saved across a reload", async () => {
    await page.click('.gr-theme button:has-text("فاتح")'); await page.waitForTimeout(300);
    must((await page.getAttribute("html", "data-theme")) === "light", "not applied");
    await shot(page, `ux-${device}-more-light.png`);
    await page.reload({ waitUntil: "domcontentloaded" }); await page.waitForTimeout(800);
    const kept = await page.getAttribute("html", "data-theme");
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    must(kept === "light", "after reload " + kept);
    await page.click('[data-gr-section="market"]'); await page.waitForTimeout(1200);
    await shot(page, `ux-${device}-light.png`);
    await page.click('[data-gr-section="more"]'); await page.click('.gr-theme button:has-text("داكن")');
    return { theme_after_reload: kept, body_bg: bg };
  });
  await task(device, "position-size calculator from the user's own numbers", async () => {
    await page.click('[data-gr-section="more"]'); await page.waitForTimeout(300);
    const card = page.locator(".gr-card", { hasText: "حجم المركز من مخاطرتك" });
    const inputs = card.locator("input");
    for (const [i, v] of [[0, "10000"], [1, "1"], [2, "50"], [3, "47.5"], [4, "56"]]) await inputs.nth(i).fill(v);
    const out = await card.locator(".gr-result").textContent();
    must(/40/.test(out) && /2[.,٫]4/.test(out) && /شراء/.test(out), out);
    await shot(page, `ux-${device}-calculator.png`);
    return { result: out };
  });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.click('[data-gr-section="market"]'); await page.click("#gr-tab-leaders"); await page.waitForTimeout(400);
  await shot(page, `ux-${device}-leaders.png`);
  await browser.close();
}

// Installable + offline: the real service worker on the local server, live published data.
async function offline() {
  const browser = await chromium.launch();
  const context = await browser.newContext({ ...DEVICES.phone, locale: "ar" });
  const page = await context.newPage();
  await task("phone", "offline: last saved data with its time, no live prices", async () => {
    await page.goto(URL, { waitUntil: "domcontentloaded" });
    const manifest = await page.evaluate(async () => (await fetch(document.querySelector('link[rel="manifest"]').href)).json());
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.reload({ waitUntil: "domcontentloaded" });          // now controlled: data copies are saved
    await page.waitForFunction(() => document.querySelectorAll("#gr-list [data-gr-symbol]").length > 0, null, { timeout: 20000 });
    await page.waitForTimeout(1500);
    await context.setOffline(true);
    await context.route("**/*", (r) => r.abort("internetdisconnected"));
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => /حُفظت|لا توجد بيانات/.test(document.getElementById("gr-offline").textContent), null, { timeout: 20000 });
    const banner = await page.$eval("#gr-offline", (e) => e.textContent);
    const rows = await page.$$eval("#gr-list [data-gr-symbol]", (els) => els.length);
    must(/غير متصل/.test(banner) && /حُفظت/.test(banner) && rows > 0, banner);
    await shot(page, "ux-phone-offline.png");
    await context.unroute("**/*");
    await context.setOffline(false);
    return { banner, rows, manifest: { name: manifest.short_name, display: manifest.display, icons: manifest.icons.length } };
  });
  // A real update: the served sw.js is replaced on disk (SW_FILE), then restored. Without SW_FILE it is not run.
  const swFile = process.env.SW_FILE;
  if (!swFile) { console.log("NOT RUN phone | service worker update (set SW_FILE to the served sw.js)"); }
  else await task("phone", "a new service worker version takes over and the page reloads once", async () => {
    const fs = require("fs");
    const original = fs.readFileSync(swFile, "utf8");
    // A fresh context: the offline toggles above must not leak into this one.
    const fresh = await browser.newContext({ ...DEVICES.phone, locale: "ar" });
    const page = await fresh.newPage();
    await page.goto(URL, { waitUntil: "domcontentloaded" });
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.reload({ waitUntil: "load" });     // fully loaded before reloads are counted
    await page.waitForFunction(() => !!navigator.serviceWorker.controller, null, { timeout: 10000 });
    const before = await page.evaluate(async () => (await caches.keys()).filter((k) => k.startsWith("ghazi-shell-")));
    try {
      fs.writeFileSync(swFile, original.replace(/const VERSION = "[^"]+"/, 'const VERSION = "ux-update-test"'));
      let loads = 0;
      page.on("load", () => { loads += 1; });
      const reloaded = page.waitForEvent("load", { timeout: 20000 });
      await page.evaluate(async () => (await navigator.serviceWorker.getRegistration()).update());
      await reloaded;
      await page.waitForFunction(async () => (await caches.keys()).includes("ghazi-shell-ux-update-test"), null, { timeout: 15000 });
      await page.waitForTimeout(2500);
      var reloads = loads;
    } finally { fs.writeFileSync(swFile, original); }
    const after = await page.evaluate(async () => (await caches.keys()).filter((k) => k.startsWith("ghazi-shell-")));
    must(after.length === 1 && after[0] === "ghazi-shell-ux-update-test" && reloads === 1, after.join(",") + " reloads " + reloads);
    return { shell_before: before, shell_after: after, reloads };
  });
  await browser.close();
}

(async () => {
  for (const d of Object.keys(DEVICES)) await run(d);
  await offline();
  fs.writeFileSync(path.join(OUT, "ux_tasks.json"), JSON.stringify(report, null, 1));
  for (const t of report.tasks) console.log(`${t.ok ? "PASS" : "FAIL"} ${t.device} | ${t.name} | ${t.ok ? JSON.stringify(t.evidence).slice(0, 220) : t.error}`);
  const failed = report.tasks.filter((t) => !t.ok).length;
  console.log(`${report.tasks.length - failed}/${report.tasks.length} tasks passed`);
  process.exit(failed ? 1 : 0);
})();
