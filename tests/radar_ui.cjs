"use strict";
// New home page (public/radar.js): pure helpers and page contract.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const R = require("../public/radar.js");

const html = fs.readFileSync(path.join(__dirname, "../public/index.html"), "utf8");
const js = fs.readFileSync(path.join(__dirname, "../public/radar.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "../public/radar.css"), "utf8");

// --- page contract: order and the five tabs ---
const order = ["gr-top", "gr-summary", "gr-tabs", "gr-main"].map((c) => html.indexOf(`class="${c}`));
assert.ok(order.every((i, k) => i > 0 && (k === 0 || i > order[k - 1])), "top bar, summary, tabs, content in that order");
for (const t of ["indices", "leaders", "small", "options", "news"]) assert.ok(html.includes(`data-gr-tab="${t}"`), t);
assert.ok(!/class="hero"|eyebrow|terminal-intro/.test(html), "no long intro block before the data");
assert.ok(html.includes('href="./classic.html?panel=trust"'), "data center link (rights, logs, operations)");
assert.ok(html.includes('href="./trading-readiness.html"'));
// One font family, 16px base, small type floor of 14px.
assert.strictEqual((html.match(/fonts\.googleapis\.com\/css2\?family=/g) || []).length, 1);
assert.ok(html.includes("family=IBM+Plex+Sans+Arabic") && html.includes("display=swap"));
assert.ok(/body \{[^}]*font-size: var\(--t-md\)/.test(css) && css.includes("--t-md: 1rem"));
const sizes = [...css.matchAll(/font-size:\s*([0-9.]+)rem/g)].map((m) => Number(m[1]));
assert.ok(sizes.every((s) => s >= 0.875), "no text below 14px: " + sizes);
// The page reads published bot-state files only; prices come only from TradingView embeds.
const urls = [...js.matchAll(/https:\/\/[a-z0-9.-]+/g)].map((m) => m[0]);
for (const u of new Set(urls)) assert.ok(/raw\.githubusercontent\.com|tradingview\.com|sec\.gov/.test(u), "unexpected host " + u);
assert.ok(!/yahoo|nasdaq\.com|cboe\.com|stooq/i.test(js), "no restricted price source");

// --- session state from the published XNYS calendar ---
const plan = { generated_at: "2026-10-25T22:25:11Z", session: { today_is_session: false, today: null,
  next_session: { date: "2026-10-26", open_new_york: "09:30", close_new_york: "16:00", open_riyadh: "16:30",
    close_riyadh: "23:00", early_close: false } } };
assert.strictEqual(R.sessionState(plan, Date.parse("2026-10-26T12:00:00Z")).state, "pre");     // 08:00 NY
assert.strictEqual(R.sessionState(plan, Date.parse("2026-10-26T14:00:00Z")).state, "open");    // 10:00 NY
assert.strictEqual(R.sessionState(plan, Date.parse("2026-10-26T21:00:00Z")).state, "after");   // 17:00 NY
assert.strictEqual(R.sessionState(plan, Date.parse("2026-10-25T23:00:00Z")).state, "closed");  // Sunday
const early = { session: { today: { date: "2026-11-27", open_new_york: "09:30", close_new_york: "13:00",
  open_riyadh: "17:30", close_riyadh: "21:00", early_close: true } } };
const half = R.sessionState(early, Date.parse("2026-11-27T19:00:00Z"));                         // 14:00 NY
assert.strictEqual(half.state, "after", "early close respected");
assert.ok(R.sessionState(null, Date.parse("2026-10-27T15:00:00Z")).text.includes("تقويم العطل غير محدّث"),
  "without a calendar it says so");

// --- events: administrative updates never presented as results ---
const doc = { generated_at: "2026-10-26T05:00:00Z", watchlist: [
  { symbol: "AMGN", universe: "KNOWN_LARGE_ISSUER_LIST", catalysts: [
    { symbol: "AMGN", kind: "TRIAL_REGISTRY_UPDATE", date: "2026-10-24", importance: "LOW", label: "x", reason: "Admin study",
      source_url: "https://clinicaltrials.gov/study/NCT00000001" },
    { symbol: "AMGN", kind: "TRIAL_RESULTS_POSTED", date: "2026-10-23", importance: "MEDIUM", label: "x",
      reason: "Study of AMG 256", source_url: "https://clinicaltrials.gov/study/NCT00000002" }] },
  { symbol: "GSK", universe: "KNOWN_LARGE_ISSUER_LIST", catalysts: [
    { symbol: "GSK", kind: "FDA_APPROVAL", date: "2026-10-20", importance: "HIGH", label: "HIBSAGO",
      source_url: "https://www.accessdata.fda.gov/x", source_updated: "2026-10-23", first_seen_at: "2026-10-26T05:00:00Z" }] },
  { symbol: "ACAD", universe: "MARKET_CAP_UNVERIFIED", catalysts: [
    { symbol: "ACAD", kind: "FDA_SUPPLEMENT", date: "2026-10-16", importance: "LOW", label: "DAYBUE STIX", issuer: "ACADIA PHARMS INC" }] },
  { symbol: "BAD!", catalysts: [{ symbol: "BAD!", kind: "FDA_APPROVAL", date: "2026-10-20" }] }] };
const events = R.eventRows(doc);
assert.deepStrictEqual(events.map((e) => e.symbol), ["AMGN", "AMGN", "GSK", "ACAD"], "valid symbols only, newest first");
assert.strictEqual(R.kindInfo("TRIAL_REGISTRY_UPDATE").group, "admin");
assert.ok(R.kindInfo("TRIAL_REGISTRY_UPDATE").label.includes("ليس نتيجة"));
assert.ok(R.kindInfo("TRIAL_RESULTS_POSTED").label.includes("الاتجاه غير محدد"));
assert.ok(R.filterEvents(events, "important").every((e) => e.info.group !== "admin"));
assert.strictEqual(R.headline(events.filter((e) => e.symbol === "AMGN")).kind, "TRIAL_RESULTS_POSTED", "admin never the headline");
assert.strictEqual(R.eventText(events[1]), "Study of AMG 256", "registry rows show the study, not a repeated type");
// Three separate times: event, source update, our first detection.
const gsk = events.find((e) => e.symbol === "GSK");
assert.ok(/تاريخ الحدث .*تحديث المصدر .*رصدناه /.test(R.timesLine(gsk)), R.timesLine(gsk));
assert.ok(!R.timesLine(events.find((e) => e.symbol === "ACAD")).includes("رصدناه"), "no detection time when unknown");
// The builder's flat events list wins over per-ticker catalysts.
assert.strictEqual(R.eventRows({ events: [{ symbol: "ZZZ", kind: "FDA_APPROVAL", date: "2026-10-01" }], watchlist: doc.watchlist }).length, 1);

// --- tabs ---
const dir = { count: 2, symbols: [
  { symbol: "AMGN", name: "Amgen", sector: "Health Care", sector_ar: "الرعاية الصحية", cik: "0000318154" },
  { symbol: "NVDA", name: "Nvidia", sector: "Information Technology", sector_ar: "تقنية المعلومات", cik: "0001045810" }] };
const leaders = R.leaderRows(dir, events, "core", "latest", doc);
assert.strictEqual(leaders[0].symbol, "AMGN", "a real event ranks first");
assert.ok(leaders.some((r) => r.symbol === "GSK" && r.tags.some((t) => t.text.includes("خارج S&P 500"))), "large foreign issuer listed as such");
assert.ok(leaders.find((r) => r.symbol === "NVDA").quiet, "no event: said quietly, once");
assert.deepStrictEqual(R.leaderRows(dir, events, "Information Technology", "symbol", doc).map((r) => r.symbol), ["NVDA"]);
const small = R.smallRows(doc, dir, events);
assert.deepStrictEqual(small.map((r) => r.symbol), ["ACAD"]);
assert.ok(small[0].tags.some((t) => t.text === "الحجم غير موثق"), "size never claimed without a permitted price");
assert.strictEqual(small[0].name, "ACADIA PHARMS INC");
const idx = R.indexRows({ cftc_index_futures: { ES: { available: true, positions_as_of: "2026-10-20",
  categories: { asset_manager: { net: 901377, weekly_change: -14458 } } } } });
assert.ok(idx[0].why.includes("صافي شراء") && idx[0].why.includes("▼"), "direction in words and symbol, not colour only");
assert.ok(R.indexRows({}).every((r) => r.why.includes("غير منشورة")));

// --- search ---
const index = R.searchIndex(dir, events);
assert.strictEqual(R.suggest(index, "nv")[0].symbol, "NVDA");
assert.strictEqual(R.suggest(index, "amgen")[0].symbol, "AMGN");
assert.strictEqual(R.suggest(index, "SPY")[0].symbol, "SPY");
assert.deepStrictEqual(R.suggest(index, ""), []);

// --- options calculator: arithmetic only ---
assert.deepStrictEqual(R.optionMath({ type: "CALL", strike: 200, premium: 3.5, contracts: 2, spot: 195 }),
  { breakeven: 203.5, max_loss: 700, move_pct: 4.36 });
assert.strictEqual(R.optionMath({ type: "PUT", strike: 200, premium: 3.5, contracts: 1 }).breakeven, 196.5);
assert.strictEqual(R.optionMath({ type: "CALL", strike: 0, premium: 1 }), null);

console.log("radar_ui ok");
