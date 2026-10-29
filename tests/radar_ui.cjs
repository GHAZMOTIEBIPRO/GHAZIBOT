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
for (const t of ["indices", "leaders", "small", "options"]) assert.ok(html.includes(`data-gr-tab="${t}"`), t);
for (const t of ["market", "radar", "news", "watch", "more"]) assert.ok(html.includes(`data-gr-section="${t}"`), t);
assert.ok(html.includes('rel="manifest"') && html.includes("apple-touch-icon"), "installable");
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
for (const u of new Set(urls)) assert.ok(/raw\.githubusercontent\.com|tradingview\.com|sec\.gov|cdn\.jsdelivr\.net/.test(u), "unexpected host " + u);
// the CDN serves one pinned chart library (code, not data) and nothing else
const cdn = [...js.matchAll(/https:\/\/cdn\.jsdelivr\.net\/[^"'\s]+/g)].map((m) => m[0]);
assert.ok(cdn.length && cdn.every((u) => u === "https://cdn.jsdelivr.net/npm/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js"), cdn);
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
// Separate times: event, source update, and our fetch only when the fetch itself is the evidence.
const gsk = events.find((e) => e.symbol === "GSK");
assert.ok(!/رصدناه|أول جلب/.test(R.timesLine(gsk)), "a list or commit time alone is not shown as an observation");
const fetched = { ...gsk, first_observed_at: "2026-10-27T15:04:13Z", first_observed_basis: "SOURCE_FEED_FETCH",
  timestamp_basis: "observed:SOURCE_FEED_FETCH;published:SOURCE_FEED_COMMIT" };
assert.ok(/تاريخ الحدث .*تحديث المصدر .*أول جلب لدينا /.test(R.timesLine(fetched)), R.timesLine(fetched));
const firstFetch = { ...gsk, first_observed_at: "2026-10-27T19:36:00Z", first_observed_basis: "FIRST_FETCH_OF_SOURCE",
  timestamp_basis: "observed:FIRST_FETCH_OF_SOURCE;published:SOURCE_FEED_FIRST_COMMIT" };
assert.ok(/جُلب مع أول تشغيل للمصدر/.test(R.timesLine(firstFetch)) && !/أول جلب لدينا/.test(R.timesLine(firstFetch)));
assert.ok(!R.timesLine(events.find((e) => e.symbol === "ACAD")).includes("جلب"), "no fetch time when unknown");
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
// Arabic: folded letters (أ/ا, ة/ه, ى/ي) match a known Arabic name; sectors are searchable in Arabic.
assert.strictEqual(R.suggest(index, "انفيديا")[0].symbol, "NVDA");
assert.strictEqual(R.suggest(index, "إنفيديا")[0].symbol, "NVDA");
assert.strictEqual(R.foldAr("مُفلسة"), "مفلسه");
// The Nasdaq Listed file widens search with its own names; nothing is invented for a symbol outside it.
const nl = { schema: "ghazi.nasdaq_listed.v1", file_created_at: "2026-10-27T18:01:00+00:00",
  rows: [["SOUN", "SoundHound AI, Inc.", "Class A Common Stock", "G", "N", 0, 1],
    ["AACG", "ATA Creativity Global", "American Depositary Shares", "G", "D", 0, 1],
    ["QQQ", "Invesco QQQ Trust, Series 1", "", "G", "N", 1, 0], ["bad", "x", "", "Q", "N", 0, 1]] };
const nm = R.nasdaqMap(nl);
assert.strictEqual(nm.size, 3, "invalid symbols dropped");
assert.strictEqual(nm.get("SOUN").tier, "ناسداك Global Market");
const wide = R.searchIndex(dir, events, nm);
assert.strictEqual(R.suggest(wide, "soundhound")[0].symbol, "SOUN");
assert.ok(!wide.some((it) => it.symbol === "ZZZZ"));
assert.strictEqual(R.nasdaqMap({ schema: "other", rows: nl.rows }).size, 0);
// Listing flags are risks, never catalysts.
const flags = R.flagRows(nl);
assert.deepStrictEqual(flags.map((r) => r.symbol), ["AACG"]);
assert.ok(flags[0].tags[0].kind === "risk" && /تنبيه ناسداك/.test(flags[0].why));
// The count is traceable: shares by code, other flagged securities (warrants, rights, units) apart.
const nl2 = { ...nl, rows: [...nl.rows, ["ABCDW", "Abcd Corp", "Warrant", "S", "D", 0, 0], ["EFGH", "Efgh Inc", "Common Stock", "S", "E", 0, 1]] };
assert.deepStrictEqual(R.flagSummary(nl2), { all: 3, equity: 2, other: 1, by_status: { D: 1, E: 1 } });
assert.strictEqual(R.flagRows(nl2).length, R.flagSummary(nl2).equity);

// --- companies vs securities: share classes are one company ---
assert.deepStrictEqual(R.companyCounts({ symbols: [{ symbol: "GOOGL", cik: "1652044" }, { symbol: "GOOG", cik: "1652044" },
  { symbol: "NVDA", cik: "1045810" }] }), { securities: 3, companies: 2 });

// --- Federal Register general notices and the news distribution ---
const fr = { schema: "ghazi.federal_register_feed.v1",
  company_unlinked: [{ date: "2026-10-27", agency: "FAA", kind: "FR_AIRWORTHINESS_DIRECTIVE", title: "Airworthiness Directives; Airbus SAS Airplanes",
    source_url: "https://www.federalregister.gov/documents/2026/10/27/x/y", unmatched: [{ name: "Airbus SAS", reason: "LISTED_OUTSIDE_US" }] }],
  general: [{ date: "2026-10-26", agency: "FDA", title: "Guidance", source_url: "https://www.federalregister.gov/d/2" },
    { date: "2026-10-26", agency: "FDA", title: "bad link", source_url: "http://evil.example" }] };
const gen = R.generalRows(fr);
assert.strictEqual(gen.length, 2, "unsafe links dropped");
assert.ok(gen[0].why.includes("مدرجة خارج أمريكا") && gen[0].label.includes("⚠"));
assert.deepStrictEqual(R.generalRows({ schema: "x" }), []);
assert.deepStrictEqual(R.filterEvents(events, "general"), [], "general notices are not ticker events");
for (const k of ["FR_AIRWORTHINESS_DIRECTIVE", "FR_FTC_CONSENT_ORDER"]) assert.strictEqual(R.kindInfo(k).group, "risk", "safety and enforcement notices are risks");
assert.ok(!/إيجابي/.test(R.kindInfo("FR_PRIORITY_REVIEW_VOUCHER").label));
const dist = R.newsDistribution(events, (s) => (s === "AMGN" ? "الرعاية الصحية" : null), Date.parse("2026-10-27T12:00:00Z"));
assert.strictEqual(dist.total, events.length);
assert.strictEqual(dist.source.reduce((a, [, v]) => a + v, 0), events.length);
assert.strictEqual(dist.age.reduce((a, [, v]) => a + v, 0), events.length);

// --- wording: a gap is scoped to the use and the sources tested; options data split by kind ---
assert.ok(!/لا يوجد مصدر مجاني/.test(js), "no blanket 'no free source' verdict");
assert.ok(R.GAP_AR.includes("ضمن المصادر التي اختبرناها"));
assert.strictEqual(R.OPTION_DATA_KINDS.length, 6);
// A source being added is not shown as a detection.
assert.ok(/أُضيف مع إدخال المصدر/.test(R.timesLine({ date: "2026-10-20", first_seen_at: "2026-10-27T10:00:00Z", first_seen_basis: "SOURCE_ADDED" })));

// --- options calculator: arithmetic only ---
assert.deepStrictEqual(R.optionMath({ type: "CALL", strike: 200, premium: 3.5, contracts: 2, spot: 195 }),
  { breakeven: 203.5, max_loss: 700, move_pct: 4.36 });
assert.strictEqual(R.optionMath({ type: "PUT", strike: 200, premium: 3.5, contracts: 1 }).breakeven, 196.5);
assert.strictEqual(R.optionMath({ type: "CALL", strike: 0, premium: 1 }), null);
// --- linked official document: entity/relation, link confidence and impact are separate; impact unassessed ---
const ad = { kind: "FR_AIRWORTHINESS_DIRECTIVE", issuer: "The Boeing Company", link_relation: "SAME_ENTITY",
  interpretation_confidence: "HIGH", potential_impact: "NEEDS_IMPACT_ASSESSMENT" };
assert.strictEqual(R.readingLine(ad), "الجهة في الوثيقة: The Boeing Company (الشركة نفسها) · ثقة الربط: عالية · الأثر: يحتاج تقييم الأثر");
assert.ok(/الأثر: يحتاج تقييم الأثر$/.test(R.readingLine({ kind: "FR_FTC_CONSENT_ORDER", link_relation: "WHOLLY_OWNED_SUBSIDIARY" })));
assert.strictEqual(R.readingLine({ kind: "FDA_APPROVAL" }), "", "events without a reviewed link carry no reading line");
// a joint venture: linked as indirect exposure with its share; the impact still unassessed
const jvLine = R.readingLine({ kind: "FR_PROPOSED_AIRWORTHINESS_DIRECTIVE", issuer: "CFM International, S.A.", link_relation: "JOINT_VENTURE_PARTNER",
  exposure: "INDIRECT", ownership_share: 0.5, relation_as_of: "2026-10-29", interpretation_confidence: "MEDIUM", potential_impact: "NEEDS_IMPACT_ASSESSMENT" });
assert.ok(/مشروع مشترك/.test(jvLine) && /ارتباط غير مباشر \(الحصة 50%\)/.test(jvLine) && /ثقة الربط: متوسطة/.test(jvLine) && /يحتاج تقييم الأثر/.test(jvLine), jvLine);
// a federal contract action: this action, the award so far and its ceiling side by side, never one summed figure
const govLine = R.readingLine({ kind: "GOV_CONTRACT_ACTION", action_obligation: 250e6, award_total_obligation: 9.1e9,
  award_ceiling: 2e10, potential_impact: "NEEDS_IMPACT_ASSESSMENT" });
assert.ok(/هذا الإجراء: 250 مليون\$/.test(govLine) && /إجمالي الملتزم على العقد: 9,100 مليون\$/.test(govLine.replace(/٬/g, ","))
  && /ليس مالًا ملتزمًا/.test(govLine) && /يحتاج تقييم الأثر$/.test(govLine), govLine);
assert.strictEqual(R.kindInfo("GOV_CONTRACT_DEOBLIGATION").group, "regulatory");
// official IR news: the headline is the company's, the category is ours, the impact unassessed
const irItem = { kind: "IR_EARNINGS", category_basis: "HEADLINE_KEYWORDS", potential_impact: "NEEDS_IMPACT_ASSESSMENT" };
assert.strictEqual(R.readingLine(irItem), "العنوان من الشركة؛ التصنيف آلي من كلماته · الأثر: يحتاج تقييم الأثر");
assert.strictEqual(R.kindInfo("IR_FILING_REGISTRATION").group, "risk");
assert.ok(R.FILTERS.some(([k]) => k === "company"));
const irEvents = R.eventRows({ events: [{ symbol: "XOM", kind: "IR_EARNINGS", date: "2026-10-30", reason: "ExxonMobil Announces Third Quarter 2026 Results", label: "نتائج مالية" }] });
assert.strictEqual(R.eventText(irEvents[0]), "ExxonMobil Announces Third Quarter 2026 Results", "the company's headline, not our label");
assert.strictEqual(R.filterEvents(irEvents, "company").length, 1);
assert.ok(/الموعد المعلن/.test(R.timesLine({ date: "2026-10-28", scheduled_for: "2026-11-17" })));
assert.ok(!/الموعد المعلن/.test(R.timesLine({ date: "2026-10-28" })));
// --- week agenda: grouped by date, each item with where its date comes from ---
const ag = R.agendaGroups({ schema: "ghazi.week_agenda.v1", items: [
  { date: "2026-11-03", kind: "COMPANY_SCHEDULE", symbol: "NVDA", basis: "COMPANY_ANNOUNCED", title_ar: "موعد أعلنته الشركة",
    title: "11/03/2026 : Example call", source_url: "https://investor.nvidia.com/e/1" },
  { date: "2026-11-02", kind: "RULE_EFFECTIVE", symbols: ["BA"], basis: "FEDERAL_REGISTER_EFFECTIVE_ON", title_ar: "يسري مفعول وثيقة رسمية" },
  { date: "2026-11-26", kind: "MARKET_CLOSED", basis: "EXCHANGE_CALENDAR", title_ar: "السوق الأمريكي مغلق (عطلة رسمية)" },
  { date: "bad", basis: "EXCHANGE_CALENDAR", title_ar: "x" }] });
assert.deepStrictEqual(ag.map((g) => g.date), ["2026-11-03", "2026-11-02", "2026-11-26"]);
assert.ok(/NVDA · موعد أعلنته الشركة · «11\/03\/2026 : Example call»/.test(ag[0].items[0].text) && ag[0].items[0].basis === "أعلنته الشركة");
assert.strictEqual(ag[2].items[0].text, "السوق الأمريكي مغلق (عطلة رسمية)");
assert.deepStrictEqual(R.agendaGroups({ schema: "other", items: [] }), []);
// --- position size from the user's own risk: arithmetic only ---
assert.deepStrictEqual(R.positionMath({ capital: "10000", risk_pct: "1", entry: "50", stop: "47.5", target: "56" }),
  { side: "LONG", shares: 40, capped_by_cash: false, risk_per_share: 2.5, stop_pct: 5, max_loss: 100, position_value: 2000,
    r_multiple: 2.4, gain_at_target: 240 });
const short = R.positionMath({ capital: 10000, risk_pct: 1, entry: 50, stop: 52, target: 55 });
assert.strictEqual(short.side, "SHORT"); assert.strictEqual(short.shares, 50); assert.strictEqual(short.target_invalid, true);
assert.strictEqual(short.r_multiple, undefined);
const capped = R.positionMath({ capital: 1000, risk_pct: 50, entry: 100, stop: 99 });
assert.strictEqual(capped.shares, 10); assert.strictEqual(capped.capped_by_cash, true); assert.strictEqual(capped.max_loss, 10);
for (const bad of [{ entry: 50, stop: 50 }, { entry: 50, stop: 49, risk_pct: 0 }, { entry: 50, stop: 49, risk_pct: 150 }, { entry: 0, stop: 1 }])
  assert.strictEqual(R.positionMath({ capital: 1000, risk_pct: 1, ...bad }), null, JSON.stringify(bad));

// --- price-analysis funnel: counts per stage, reason when bars are not fetched ---
const fl = R.funnelLine({ known_symbols: { count: 5615 }, with_official_news: { count: 120 },
  bars_fetched: { count: 0, status: "DATA_USE_PERMISSION_REQUIRED" }, analysed: { count: 0 }, qualified: { count: null } });
assert.ok(/معروفة .*لها أخبار .*جُلبت شموعها 0 \(بانتظار إعداد مسار البيانات الخاص\)/.test(fl), fl);

// --- contrast: every text colour on bg / surface / surface-2 clears WCAG AA in both themes ---
const tokens = (block) => Object.fromEntries([...block.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]));
const darkTokens = tokens(css.slice(css.indexOf(":root {"), css.indexOf("}", css.indexOf(":root {"))));
const lightStart = css.indexOf(':root[data-theme="light"]');
const lightTokens = { ...darkTokens, ...tokens(css.slice(lightStart, css.indexOf("}", lightStart))) };
const lum = (h) => { const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
  .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
const contrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
for (const [theme, t] of [["dark", darkTokens], ["light", lightTokens]]) {
  for (const fg of ["text", "text-2", "text-3", "accent", "ok", "warn", "risk"]) {
    for (const bg of ["bg", "surface", "surface-2"]) {
      const r = contrast(t[fg], t[bg]);
      assert.ok(r >= 4.5, `${theme} ${fg} on ${bg}: ${r.toFixed(2)}`);
    }
  }
}
assert.ok(lightStart > 0 && darkTokens.bg === "#0b1220", "two themes from tokens");

// platform state: three separate answers, a word and a shape per state, never one "trust" number
{
  const now = Date.parse("2026-10-29T03:00:00Z");
  const cards = { scorecards: {
    SYSTEM_RELIABILITY: { status: "MEASURED", value: 100 }, WEBSITE_FUNCTIONALITY: { value: 100 },
    TELEGRAM_DELIVERY: { evidence: { last_sent_at: "2026-10-28T18:23:39Z", message_id: 1316 } },
    SIGNAL_PERFORMANCE: { status: "NO_PROVEN_EDGE", evidence: { walk_forward: { research_passed: false }, spa: { pvalue_consistent: 0.498 } } } } };
  const log = { schema: "ghazi.source_log.v1", window_days: 14, sources: [
    { key: "alpaca_bars", name_ar: "شموع Alpaca", last_outcome: "NOT_ATTEMPTED", last_detail: "ACCOUNT_CREDENTIALS_NOT_CONFIGURED", attempted: 0 },
    { key: "sec_edgar", name_ar: "SEC EDGAR", last_outcome: "FAILED", attempted: 8, succeeded: 0 },
    { key: "treasury", name_ar: "الخزانة", last_outcome: "OK", attempted: 4, succeeded: 4, last_success_at: "2026-10-29T01:57:01Z" },
    { key: "clinicaltrials", name_ar: "ClinicalTrials.gov", last_outcome: "PARTIAL", attempted: 12, succeeded: 12 }] };
  const [run, data, sig] = R.platformState(cards, log, now);
  assert.deepStrictEqual([run.title, data.title, sig.title], ["سلامة التشغيل", "جودة البيانات وتغطيتها", "أداء الإشارات المقاس"]);
  assert.ok(run.state === "good" && run.mark === "✓" && /100%/.test(run.line));
  assert.ok(data.state === "bad" && /تعمل 2 مصادر \(1 جزئيًا\)، و1 موقوفة بشرط أو مفتاح، ويفشل الجلب من: SEC EDGAR\./.test(data.line), data.line);
  assert.ok(/شموع الأسعار لتحليلنا غير متاحة بعد/.test(data.line));
  const alp = data.details.find((d) => /Alpaca/.test(d.text));
  assert.ok(alp.mark === "⏸" && /ينتظر مفاتيح الحساب/.test(alp.text) && !/0\/0/.test(alp.text), alp.text);
  assert.ok(/4\/4 جلب ناجح خلال 14 يومًا/.test(data.details.find((d) => /الخزانة/.test(d.text)).text));
  assert.ok(sig.state === "partial" && /لا أفضلية مثبتة/.test(sig.line) && sig.details.some((t) => /p = 0.498/.test(t)));
  for (const b of [run, data, sig]) assert.ok(!/ثقة \d|trust/i.test(b.line), "no combined trust figure");
  // missing files: each answer says so on its own
  const empty = R.platformState(null, null, now);
  assert.deepStrictEqual(empty.map((b) => b.state), ["none", "none", "none"]);
}

{
  // liquidity facts: own dates, freshness words, and the New York Fed notice with SOFR
  const liq = {
    claims: { available: true, initial_claims: 199871, initial_claims_yoy_pct: -3.2, week_ending: "2026-10-17", stale: false },
    funding_rates: { available: true, sofr: { rate: 3.95, date: "2026-10-27" }, target_range: [3.75, 4.0],
      notice: { SOFR: "The SOFR is subject to the Terms of Use posted at newyorkfed.org.", dtcc: "DTCC Solutions LLC note." } } };
  const facts = R.liquidityFacts(liq, Date.parse("2026-10-29T15:00:00Z"));
  assert.deepStrictEqual(facts.map((f) => f.key), ["claims", "sofr"]);
  assert.ok(/غير معدّلة موسميًا/.test(facts[0].label) && /قبل عام/.test(facts[0].sub) && /−3.2%/.test(facts[0].sub), facts[0].sub);
  assert.ok(facts[1].value === "3.95%" && /3.75–4.00%/.test(facts[1].sub));
  assert.ok(/newyorkfed.org/.test(facts[1].notice) && /DTCC/.test(facts[1].notice));
  // old or kept copies say so; missing comparisons are not shown as zero
  const old = R.liquidityFacts({ claims: { ...liq.claims, stale: true, age_days: 40, initial_claims_yoy_pct: null },
    funding_rates: { ...liq.funding_rates, kept_previous_copy: true } }, Date.now());
  assert.ok(/قديمة \(عمرها 40 يومًا\)/.test(old[0].sub) && /لا مقارنة سنوية/.test(old[0].sub));
  assert.ok(/آخر قيمة منشورة/.test(old[1].sub));
  assert.deepStrictEqual(R.liquidityFacts({ claims: { available: false }, funding_rates: { available: false } }), []);
  assert.deepStrictEqual(R.liquidityFacts(null), []);
  // reading + chart series: computed fields only, observation vs publication dates apart
  const rd = R.liquidityReading({
    claims: { available: true, initial_claims_4wk_avg: 173074, initial_claims_4wk_avg_year_ago: 199974, initial_claims_4wk_yoy_pct: -13.5,
      band_4wk_vs_year_ago: "LOWER", continued_weeks_claimed: 1472151, continued_reflect_week: "2026-10-10", continued_yoy_pct: -11.7,
      week_ending: "2026-10-17", source_last_modified: "Wed, 28 Oct 2026 19:50:59 GMT",
      chart_52w: [["2026-10-10", 191099, 210105], ["2026-10-17", 172640, null]] },
    funding_rates: { available: true, sofr: { rate: 3.95, date: "2026-10-27" }, target_range: [3.75, 4.0], days_p99_above_target_top: 2, window_days: 60,
      sofr_history: [["2026-10-26", 3.93, 4.01, 4.0], ["2026-10-27", 3.95, 4.04, 4.0]], notice: { SOFR: "The SOFR is subject to the Terms of Use posted at newyorkfed.org." } },
    repo: { available: true, tri_party_rate: { available: true, value: 3.92, change_bp: 2, date: "2026-10-26" },
      tri_party_volume: { available: true, value: 2.1e12, change_pct: 4.2 } } });
  assert.ok(/173,074 مقابل 199,974/.test(rd.lines[0]) && /أقل من الفترة نفسها قبل عام/.test(rd.lines[0]), rd.lines[0]);
  assert.ok(rd.lines.some((l) => /تجاوز المئين 99 سقف النطاق في 2 من آخر 60/.test(l)));
  assert.ok(rd.lines.some((l) => /الريبو الثلاثي لليلة 3.92%/.test(l) && /2,100 مليار دولار/.test(l)));
  assert.ok(/لا تقيس تدفقًا إلى سهم بعينه/.test(rd.lines[rd.lines.length - 1]));
  assert.deepStrictEqual(rd.claims.yearAgo, [{ time: "2026-10-10", value: 210105 }]); // a missing year-ago week is skipped, not 0
  assert.ok(/أسبوع الملاحظة الأخير حتى/.test(rd.captions.claims) && /نشرت وزارة العمل الملف/.test(rd.captions.claims));
  assert.ok(rd.sofr.top.length === 2 && /newyorkfed/.test(rd.notice));
  // a kept copy is not read as current
  assert.deepStrictEqual(R.liquidityReading({ claims: { available: true, kept_previous_copy: true, initial_claims_4wk_avg: 1, initial_claims_4wk_avg_year_ago: 1 } }).lines, []);
}

console.log("radar_ui ok");
