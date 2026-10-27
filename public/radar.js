"use strict";
// GHAZI RADAR home page: one list per market tab, one detail view per symbol.
//
// Data: the published bot-state files only (official events, macro, the
// leaders directory). Prices are never fetched or shown by this page; the
// chart and the price tape are TradingView embeds that render their own data
// in the visitor's browser and are never read back. Missing data is said once,
// next to the information it affects, and its details stay behind a toggle.
(function (root) {
  const DATA = "https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/";
  const FILES = { plan: "daily_plan.json", macro: "public_macro.json", catalysts: "catalyst_watchlist.json",
    directory: "symbol_directory.json", options: "options_analytics.json", fr: "federal_register.json" };
  const NASDAQ_FILE = "nasdaq_listed.json";   // ~5,600 rows: loaded only when search or a view needs it
  const SYMBOL_RE = /^[A-Z][A-Z0-9.-]{0,9}$/;
  const WATCH_KEY = "ghazi.watchlist.v1";      // same key as the previous page, so saved lists carry over
  const CHART_TIMEOUT_MS = 15000;
  const TAPE_SRC = "https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js";
  const NUM = typeof Intl !== "undefined" ? new Intl.NumberFormat("ar-u-nu-latn") : null;
  const DAY = typeof Intl !== "undefined" ? new Intl.DateTimeFormat("ar-u-nu-latn", { day: "numeric", month: "long", timeZone: "UTC" }) : null;
  const REL = typeof Intl !== "undefined" && Intl.RelativeTimeFormat ? new Intl.RelativeTimeFormat("ar-u-nu-latn", { numeric: "auto" }) : null;

  // Index funds (cash indices do not render in the free embeds; the ETF is labelled as such).
  const INDEX_ROWS = [
    { symbol: "SPY", name: "صندوق يتتبع S&P 500", cftc: "ES" },
    { symbol: "QQQ", name: "صندوق يتتبع ناسداك 100", cftc: "NQ" },
    { symbol: "DIA", name: "صندوق يتتبع داو جونز", cftc: "YM" },
    { symbol: "IWM", name: "صندوق يتتبع راسل 2000", cftc: "RTY" },
  ];
  // Shown first in the leaders tab while the directory supplies names and sectors.
  const CORE_LEADERS = ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "BRK.B", "JPM", "LLY", "XOM"];
  const FALLBACK_NAMES = { NVDA: "Nvidia", AAPL: "Apple", MSFT: "Microsoft", AMZN: "Amazon", GOOGL: "Alphabet",
    META: "Meta Platforms", AVGO: "Broadcom", TSLA: "Tesla", "BRK.B": "Berkshire Hathaway", JPM: "JPMorgan Chase",
    LLY: "Eli Lilly", XOM: "ExxonMobil" };

  // ---------- formatting ----------
  const n = (v) => (NUM ? NUM.format(v) : String(v));
  // A signed number kept left-to-right inside Arabic text (otherwise "+31" shows as "31+").
  const signed = (v, text) => `\u2066${v >= 0 ? "+" : "−"}${text}\u2069`;
  function compact(v) {
    const a = Math.abs(v);
    if (a >= 1e6) return n(+(v / 1e6).toFixed(1)) + " مليون";
    if (a >= 1e3) return n(Math.round(v / 1e3)) + " ألف";
    return n(v);
  }
  function day(iso) {
    const s = String(iso || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
    const d = new Date(s + "T00:00:00Z");
    return DAY ? DAY.format(d) : s;
  }
  function ago(iso, now) {
    const t = Date.parse(iso);
    if (!Number.isFinite(t)) return null;
    const minutes = Math.round((t - now) / 60000);
    const abs = Math.abs(minutes);
    if (!REL) return String(-minutes) + " min";
    if (abs < 60) return REL.format(minutes, "minute");
    if (abs < 48 * 60) return REL.format(Math.round(minutes / 60), "hour");
    return REL.format(Math.round(minutes / 1440), "day");
  }
  const safeUrl = (u) => (typeof u === "string" && /^https:\/\/[^\s"<>]+$/.test(u) ? u : null);

  // ---------- session ----------
  // New York wall time for an instant.
  function nyParts(now) {
    const f = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit",
      day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", weekday: "short" });
    const p = Object.fromEntries(f.formatToParts(new Date(now)).map((x) => [x.type, x.value]));
    return { date: `${p.year}-${p.month}-${p.day}`, minutes: Number(p.hour) * 60 + Number(p.minute), weekday: p.weekday };
  }
  const mins = (hhmm) => { const m = /^(\d{2}):(\d{2})$/.exec(String(hhmm || "")); return m ? Number(m[1]) * 60 + Number(m[2]) : null; };

  // Uses the exchange calendar published in the daily plan when its dates
  // cover today; otherwise falls back to regular hours and says so.
  function sessionState(plan, now) {
    const ny = nyParts(now);
    const s = plan && plan.session ? plan.session : {};
    const known = [s.today, s.next_session].filter((x) => x && x.date);
    const todays = known.find((x) => x.date === ny.date);
    const next = known.find((x) => x.date > ny.date) || null;
    const nextText = (x) => x ? `الجلسة القادمة ${day(x.date)} ${x.open_riyadh || ""} بتوقيت الرياض`.trim() : "";
    if (todays) {
      const open = mins(todays.open_new_york), close = mins(todays.close_new_york);
      const early = todays.early_close ? " (إغلاق مبكر)" : "";
      if (ny.minutes < open) return { state: "pre", text: `قبل الافتتاح · يفتح ${todays.open_riyadh} بتوقيت الرياض${early}` };
      if (ny.minutes < close) return { state: "open", text: `السوق مفتوح · يغلق ${todays.close_riyadh} بتوقيت الرياض${early}` };
      return { state: "after", text: `انتهت جلسة اليوم${next ? " · " + nextText(next) : ""}` };
    }
    const planDay = String((plan && plan.generated_at) || "").slice(0, 10);
    if (s.today_is_session === false && planDay && nyParts(Date.parse(plan.generated_at)).date === ny.date)
      return { state: "closed", text: `السوق مغلق اليوم${next ? " · " + nextText(next) : ""}` };
    if (next) return { state: "closed", text: `السوق مغلق · ${nextText(next)}` };
    // No calendar for today: regular hours only, said explicitly.
    const weekend = ny.weekday === "Sat" || ny.weekday === "Sun";
    const open = !weekend && ny.minutes >= 570 && ny.minutes < 960;
    return { state: open ? "open" : "closed",
      text: (open ? "مفتوح غالبًا" : "مغلق غالبًا") + " · حسب الساعات المعتادة؛ تقويم العطل غير محدّث" };
  }

  // ---------- events ----------
  const KIND = {
    FDA_APPROVAL: { label: "موافقة FDA", tag: "decision", group: "decision" },
    FDA_SUPPLEMENT: { label: "موافقة FDA تكميلية", tag: "decision", group: "decision" },
    FDA_RECALL: { label: "⚠ سحب منتج (FDA)", tag: "risk", group: "risk" },
    TRIAL_RESULTS_POSTED: { label: "نتائج دراسة منشورة · الاتجاه غير محدد", tag: "results", group: "results" },
    TRIAL_STATUS_REVIEW: { label: "تغيّر حالة دراسة (إيقاف أو تعليق أو سحب)", tag: "status", group: "risk" },
    TRIAL_REGISTRY_UPDATE: { label: "تحديث إداري في سجل دراسة · ليس نتيجة", tag: "admin", group: "admin" },
    DILUTION_RISK: { label: "⚠ طرح أو تخفيف محتمل (SEC)", tag: "risk", group: "risk" },
    CHARTER_OR_REVERSE_SPLIT_REVIEW: { label: "⚠ تعديل نظام أو تقسيم عكسي (SEC)", tag: "risk", group: "risk" },
    LISTING_NOTICE: { label: "⚠ إشعار إدراج (SEC)", tag: "risk", group: "risk" },
    // Federal Register notices: neutral labels; safety and enforcement actions are risks, never positive.
    FR_PRIORITY_REVIEW_VOUCHER: { label: "منح قسيمة مراجعة أولوية (FDA)", tag: "decision", group: "decision" },
    FR_APPROVAL_WITHDRAWN: { label: "سحب موافقة دواء جنيس (FDA)", tag: "status", group: "regulatory" },
    FR_AIRWORTHINESS_DIRECTIVE: { label: "⚠ توجيه صلاحية طيران إلزامي (FAA)", tag: "risk", group: "risk" },
    FR_PROPOSED_AIRWORTHINESS_DIRECTIVE: { label: "مقترح توجيه صلاحية طيران (FAA)", tag: "status", group: "regulatory" },
    FR_SPECIAL_CONDITIONS: { label: "شروط خاصة لاعتماد طراز طائرة (FAA)", tag: "status", group: "regulatory" },
    FR_FTC_CONSENT_ORDER: { label: "⚠ تسوية مقترحة مع FTC", tag: "risk", group: "risk" },
    FR_ENERGY_REGULATORY_FILING: { label: "إجراء لدى لجنة تنظيم الطاقة (FERC)", tag: "status", group: "regulatory" },
    FR_NUCLEAR_LICENSE_ACTION: { label: "إجراء ترخيص نووي (NRC)", tag: "status", group: "regulatory" },
  };
  const kindInfo = (k) => KIND[k] || { label: "حدث رسمي", tag: "results", group: "results" };
  const RANK = { HIGH: 3, MEDIUM: 2, LOW: 1 };

  // One flat list: the builder's events[] when present, else the per-ticker catalysts.
  function eventRows(doc) {
    if (!doc || typeof doc !== "object") return [];
    let raw = Array.isArray(doc.events) ? doc.events : [];
    if (!raw.length && Array.isArray(doc.watchlist))
      raw = doc.watchlist.flatMap((e) => (Array.isArray(e.catalysts) ? e.catalysts : []));
    const seen = new Set();
    const out = [];
    for (const e of raw) {
      if (!e || !SYMBOL_RE.test(String(e.symbol || "")) || !/^\d{4}-\d{2}-\d{2}/.test(String(e.date || ""))) continue;
      const key = [e.symbol, e.kind, e.date, e.source_url, e.label].join("|");
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ ...e, info: kindInfo(e.kind) });
    }
    return out.sort((a, b) => String(b.date).localeCompare(String(a.date)) || (RANK[b.importance] || 0) - (RANK[a.importance] || 0));
  }
  const FILTERS = [
    ["important", "المهم (دون الإداري)"], ["decision", "قرارات تنظيمية"], ["results", "نتائج دراسات"],
    ["risk", "مخاطر"], ["regulatory", "إشعارات حكومية"], ["admin", "تحديثات إدارية"], ["all", "الكل"],
    ["general", "إشعارات غير مرتبطة بسهم"],
  ];
  function filterEvents(events, filter) {
    if (filter === "all") return events;
    if (filter === "general") return [];
    if (filter === "important") return events.filter((e) => e.info.group !== "admin");
    return events.filter((e) => e.info.group === filter);
  }
  // The most telling event for a symbol: never an administrative update when another exists.
  function headline(events) {
    return events.find((e) => e.info.group !== "admin") || events[0] || null;
  }
  // What the event is about: the study title for registry events (their label
  // repeats the event type), the product for FDA events. The type itself is the tag.
  function eventText(e) {
    const text = String(/^TRIAL_/.test(e.kind) ? e.reason || e.label || "" : e.label || e.reason || "").trim();
    return text.length > 140 ? text.slice(0, 137) + "…" : text || e.info.label;
  }
  const kindTag = (e) => ({ text: e.info.label.replace(/ ·.*$/, ""), kind: e.info.tag });
  // Event date, source publication and our first detection are separate times;
  // a source being added is not a detection, and an unproven time is not shown.
  function timesLine(e) {
    const parts = [`تاريخ الحدث ${day(e.date) || e.date}`];
    if (e.source_updated && e.source_updated !== String(e.date).slice(0, 10)) parts.push(`تحديث المصدر ${day(e.source_updated)}`);
    if (e.first_seen_at && e.first_seen_basis === "SOURCE_ADDED") parts.push(`أُضيف مع إدخال المصدر ${day(e.first_seen_at)}`);
    else if (e.first_seen_at) parts.push(`رصدناه ${day(e.first_seen_at)}`);
    return parts.join(" · ");
  }

  // Federal Register documents with no reviewed link: general notices, with the company
  // named and why it is not tied to a ticker (private, joint venture, listed abroad, ...).
  const UNLINKED_AR = { PRIVATE: "شركة خاصة", JOINT_VENTURE: "مشروع مشترك", LISTED_OUTSIDE_US: "مدرجة خارج أمريكا",
    PARTLY_OWNED: "مملوكة جزئيًا", OWNERSHIP_NOT_VERIFIED: "الملكية غير متحقق منها", NOT_EXCHANGE_LISTED: "غير مدرجة في بورصة",
    NOT_A_COMPANY: "ليست شركة", NOT_IN_REVIEWED_TABLE: "لم نراجع ارتباطها بسهم" };
  function generalRows(fr) {
    if (!fr || fr.schema !== "ghazi.federal_register_feed.v1") return [];
    const rows = [];
    for (const e of [...(fr.company_unlinked || []), ...(fr.general || [])]) {
      if (!e || !safeUrl(e.source_url) || !/^\d{4}-\d{2}-\d{2}/.test(String(e.date || ""))) continue;
      const why = (e.unmatched || []).map((u) => `${u.name}: ${UNLINKED_AR[u.reason] || "غير مرتبط"}`).join(" · ");
      rows.push({ date: e.date, agency: e.agency || "", title: String(e.title || ""), url: e.source_url,
        label: e.kind ? kindInfo(e.kind).label : "إشعار عام", why });
    }
    return rows.sort((a, b) => String(b.date).localeCompare(String(a.date)));
  }

  // How the shown news is spread: by source, by type group, by age and by sector.
  const GROUP_AR = { decision: "قرارات", results: "نتائج", risk: "مخاطر", regulatory: "إشعارات حكومية", admin: "إدارية" };
  function newsDistribution(events, sectorOf, now) {
    const count = (key) => { const m = new Map(); for (const e of events) { const k = key(e); m.set(k, (m.get(k) || 0) + 1); }
      return [...m.entries()].sort((a, b) => b[1] - a[1]); };
    const age = (e) => { const d = (now - Date.parse(String(e.date).slice(0, 10) + "T00:00:00Z")) / 864e5;
      return d <= 1 ? "آخر يوم" : d <= 7 ? "آخر أسبوع" : d <= 14 ? "آخر أسبوعين" : "أقدم"; };
    return { total: events.length, source: count((e) => e.source || "غير معروف"),
      group: count((e) => GROUP_AR[e.info.group] || "أخرى"), age: count(age),
      sector: count((e) => sectorOf(e.symbol) || "قطاع غير محمّل") };
  }

  // Arabic search: letters folded so that أ/إ/آ/ا, ة/ه and ى/ي match, diacritics ignored.
  const foldAr = (s) => String(s || "").toLowerCase().replace(/[ً-ْـ]/g, "").replace(/[أإآ]/g, "ا")
    .replace(/ة/g, "ه").replace(/ى/g, "ي").replace(/\s+/g, " ").trim();
  // Arabic names for the symbols the page lists by default; other companies are found by symbol, English name or sector.
  const AR_NAMES = { NVDA: "إنفيديا", AAPL: "أبل", MSFT: "مايكروسوفت", AMZN: "أمازون", GOOGL: "ألفابت جوجل", GOOG: "ألفابت جوجل",
    META: "ميتا فيسبوك", AVGO: "برودكوم", TSLA: "تسلا", "BRK.B": "بيركشاير هاثاواي", JPM: "جي بي مورغان", LLY: "إيلي ليلي",
    XOM: "إكسون موبيل", SPY: "إس آند بي 500", QQQ: "ناسداك 100", DIA: "داو جونز", IWM: "راسل 2000", BA: "بوينغ",
    NFLX: "نتفليكس", AMD: "إيه إم دي", INTC: "إنتل", PFE: "فايزر", MRNA: "موديرنا", KO: "كوكا كولا", WMT: "وول مارت",
    DIS: "ديزني", ORCL: "أوراكل", PLTR: "بالانتير", COST: "كوستكو", V: "فيزا", MA: "ماستركارد", UNH: "يونايتد هيلث" };

  // NasdaqTrader "Nasdaq Listed" file (the product its Events Data notice covers).
  const TIER_AR = { Q: "ناسداك Global Select", G: "ناسداك Global Market", S: "ناسداك Capital Market" };
  const STATUS_AR = { D: "دون متطلبات الإدراج المستمر", E: "متأخرة في تقديم التقارير الدورية", Q: "مُفلسة",
    G: "دون متطلبات الإدراج ومُفلسة", H: "دون متطلبات الإدراج ومتأخرة في التقارير", J: "متأخرة في التقارير ومُفلسة",
    K: "دون متطلبات الإدراج ومتأخرة ومُفلسة" };
  function nasdaqMap(nl) {
    const m = new Map();
    if (!nl || nl.schema !== "ghazi.nasdaq_listed.v1" || !Array.isArray(nl.rows)) return m;
    for (const r of nl.rows) {
      if (!Array.isArray(r) || !SYMBOL_RE.test(String(r[0]))) continue;
      m.set(r[0], { symbol: r[0], name: r[1] || "", security: r[2] || "", tier: TIER_AR[r[3]] || "",
        status: r[4] && r[4] !== "N" ? r[4] : null, etf: r[5] === 1, equity: r[6] === 1 });
    }
    return m;
  }
  function flagRows(nl) {
    return [...nasdaqMap(nl).values()].filter((r) => r.status && r.equity).map((r) => ({
      symbol: r.symbol, name: r.name, why: `تنبيه ناسداك: ${STATUS_AR[r.status] || r.status}`, time: "",
      tags: [{ text: "⚠ تنبيه إدراج", kind: "risk" }, { text: r.tier, kind: "admin" }].filter((t) => t.text) }))
      .sort((a, b) => a.symbol.localeCompare(b.symbol));
  }

  // ---------- tab rows ----------
  function directoryMap(dir) {
    const m = new Map();
    for (const r of (dir && Array.isArray(dir.symbols) ? dir.symbols : [])) if (r && SYMBOL_RE.test(r.symbol)) m.set(r.symbol, r);
    return m;
  }
  function bySymbol(events) {
    const m = new Map();
    for (const e of events) { if (!m.has(e.symbol)) m.set(e.symbol, []); m.get(e.symbol).push(e); }
    return m;
  }
  function indexRows(macro) {
    const cftc = (macro && macro.cftc_index_futures) || {};
    return INDEX_ROWS.map((r) => {
      const c = cftc[r.cftc];
      const am = c && c.available && c.categories ? c.categories.asset_manager : null;
      const why = am && Number.isFinite(am.net)
        ? `مديرو الأصول في العقود الآجلة: صافي ${am.net >= 0 ? "شراء" : "بيع"} ${compact(Math.abs(am.net))} عقد` +
          (Number.isFinite(am.weekly_change) ? ` (${am.weekly_change >= 0 ? "▲" : "▼"} ${signed(am.weekly_change, compact(Math.abs(am.weekly_change)))} أسبوعيًا)` : "")
        : "مراكز العقود الآجلة غير منشورة في آخر تقرير";
      return { symbol: r.symbol, name: r.name, why, time: c && c.positions_as_of ? `مراكز ${day(c.positions_as_of)}` : "",
        tags: [{ text: "CFTC", kind: "results" }], cftc: c || null };
    });
  }
  // Large issuers the catalyst list knows that are not in the S&P 500 directory.
  // Without the directory nothing is said about membership.
  function largeOutside(doc, members) {
    return new Set((doc && Array.isArray(doc.watchlist) ? doc.watchlist : [])
      .filter((e) => e && e.universe === "KNOWN_LARGE_ISSUER_LIST" && !members.has(e.symbol)).map((e) => e.symbol));
  }
  function leaderRows(dir, events, sector, sort, doc) {
    const members = directoryMap(dir);
    const evs = bySymbol(events);
    const foreign = largeOutside(doc, members);
    let symbols;
    if (sector && sector !== "core") symbols = [...members.values()].filter((r) => r.sector === sector).map((r) => r.symbol);
    else {
      const withEvents = [...evs.keys()].filter((s) => members.has(s) || foreign.has(s));
      symbols = [...new Set([...withEvents, ...CORE_LEADERS])];
    }
    const known = members.size > 0;
    const rows = symbols.map((s, order) => {
      const meta = members.get(s);
      const list = evs.get(s) || [];
      const top = headline(list);
      const notable = top && top.info.group !== "admin";   // administrative updates never rank a company up
      // No event: the sector line, not a repeated "nothing found" (the tab note says which sources exist).
      const quietWhy = meta ? `${meta.sector_ar}${meta.sub_industry ? " · " + meta.sub_industry : ""}` : "قيادية · قطاعها غير محمّل";
      const sizeTag = meta ? null : foreign.has(s) ? { text: known ? "شركة كبيرة خارج S&P 500" : "شركة كبيرة", kind: "admin" } : null;
      return { symbol: s, name: meta ? meta.name : FALLBACK_NAMES[s] || (top && top.issuer) || "",
        why: top ? eventText(top) : quietWhy,
        quiet: !notable, time: top ? day(top.date) : "", latest: notable ? top.date : "", order,
        tags: [top && meta ? { text: meta.sector_ar, kind: "admin" } : null, sizeTag, top ? kindTag(top) : null].filter(Boolean) };
    });
    const core = (r) => (CORE_LEADERS.includes(r.symbol) ? 0 : 1);
    if (sort === "symbol") rows.sort((a, b) => a.symbol.localeCompare(b.symbol));
    else rows.sort((a, b) => String(b.latest).localeCompare(String(a.latest)) || core(a) - core(b) || a.order - b.order);
    return rows;
  }
  function smallRows(doc, dir, events) {
    const members = directoryMap(dir);
    const evs = bySymbol(events);
    const list = (doc && Array.isArray(doc.watchlist) ? doc.watchlist : [])
      .filter((e) => e && e.universe === "MARKET_CAP_UNVERIFIED" && !members.has(e.symbol));
    return list.map((e) => {
      const mine = evs.get(e.symbol) || eventRows({ watchlist: [e] });
      const top = headline(mine);
      return { symbol: e.symbol, name: (top && top.issuer) || "",
        why: top ? eventText(top) : "حدث رسمي", quiet: !top || top.info.group === "admin",
        time: top ? day(top.date) : "", latest: top ? top.date : "",
        tags: [top ? kindTag(top) : null, { text: "الحجم غير موثق", kind: "admin" }].filter(Boolean) };
    }).sort((a, b) => String(b.latest).localeCompare(String(a.latest)));
  }

  // ---------- search ----------
  // S&P 500 directory, events, the default leaders and, once loaded, every Nasdaq-listed security.
  function searchIndex(dir, events, nasdaq) {
    const items = new Map();
    const add = (symbol, fields) => items.set(symbol, { symbol, ...(items.get(symbol) || {}), ...fields });
    for (const r of nasdaq ? nasdaq.values() : []) add(r.symbol, { name: r.name, sector: r.tier });
    for (const r of INDEX_ROWS) add(r.symbol, { name: r.name });
    for (const r of directoryMap(dir).values()) add(r.symbol, { name: r.name, sector: r.sector_ar });
    for (const e of events) if (!items.has(e.symbol)) add(e.symbol, { name: e.issuer || "" });
    for (const s of CORE_LEADERS) if (!items.has(s)) add(s, { name: FALLBACK_NAMES[s] || "" });
    for (const [s, ar] of Object.entries(AR_NAMES)) if (items.has(s)) add(s, { ar });
    for (const it of items.values()) it.fold = foldAr([it.ar, it.sector].filter(Boolean).join(" "));
    return [...items.values()];
  }
  function suggest(index, query, limit = 8) {
    const q = String(query || "").trim();
    if (!q) return [];
    const up = q.toUpperCase(), low = q.toLowerCase(), ar = foldAr(q);
    const arabic = /[؀-ۿ]/.test(q);
    const scored = [];
    for (const it of index) {
      let score = -1;
      if (it.symbol === up) score = 0;
      else if (!arabic && it.symbol.startsWith(up)) score = 1;
      else if (it.name && it.name.toLowerCase().startsWith(low)) score = 2;
      else if (arabic && it.fold && it.fold.split(" ").some((w) => w.startsWith(ar))) score = 2;
      else if (it.name && it.name.toLowerCase().includes(low)) score = 3;
      else if (arabic && it.fold && it.fold.includes(ar)) score = 3;
      if (score >= 0) scored.push([score + (it.ar ? 0 : 0.5), it]);
    }
    return scored.sort((a, b) => a[0] - b[0] || a[1].symbol.length - b[1].symbol.length || a[1].symbol.localeCompare(b[1].symbol))
      .slice(0, limit).map((x) => x[1]);
  }

  // ---------- options calculator (no market data) ----------
  function optionMath({ type, strike, premium, contracts, spot }) {
    const k = Number(strike), p = Number(premium), c = Math.max(1, Math.floor(Number(contracts) || 1));
    if (!(k > 0) || !(p >= 0)) return null;
    const breakeven = type === "PUT" ? k - p : k + p;
    const out = { breakeven: +breakeven.toFixed(2), max_loss: +(p * 100 * c).toFixed(2) };
    const s = Number(spot);
    if (s > 0) out.move_pct = +(((breakeven - s) / s) * 100).toFixed(2);
    return out;
  }

  // Share classes make securities and companies different counts (GOOGL and GOOG are one company).
  function companyCounts(dir) {
    const rows = dir && Array.isArray(dir.symbols) ? dir.symbols : [];
    return { securities: rows.length, companies: new Set(rows.map((r) => r && (r.cik || r.symbol))).size };
  }
  // A gap is stated for the use in question and the sources tested, never as "no source exists".
  const GAP_AR = "لم نجد حتى الآن مصدرًا مناسبًا للاستخدام المحدد ضمن المصادر التي اختبرناها";
  // Options data by kind: each kind has its own rights and use; a subscription is not a redistribution right.
  const OPTION_DATA_KINDS = [
    ["أسعار تاريخية للعقود", GAP_AR + " للنشر على الموقع."],
    ["أسعار مؤجلة", "جداول Cboe المؤجلة تمنع الجمع الآلي؛ الجمع متوقف ولن يُعاد دون تصريح."],
    ["أسعار حية (OPRA)", "تصل عبر مزود مرخّص من OPRA؛ إعادة نشرها للعموم تحتاج اتفاقية توزيع ورسومًا منفصلة عن الاشتراك."],
    ["إحصاءات مجمّعة (حجم وعقود مفتوحة يومية)", "منشورة يوميًا، والعقود المفتوحة ليست لحظية؛ الجلب الآلي متوقف حتى مراجعة شروط الناشر."],
    ["أسعار العقود للتنفيذ (عرض/طلب)", "الخطة المجانية في Alpaca إرشادية وليست OPRA، فلا تُعد دليل تنفيذ."],
    ["نتائج مشتقة (Greeks وGamma)", "تُحسب فقط من بيانات مسموح بها، ولا تُعرض قبل توفرها."],
  ];

  const api = { sessionState, eventRows, filterEvents, headline, eventText, timesLine, indexRows, leaderRows, smallRows,
    searchIndex, suggest, optionMath, kindInfo, day, FILTERS, INDEX_ROWS, CORE_LEADERS, generalRows, newsDistribution,
    foldAr, nasdaqMap, flagRows, companyCounts, OPTION_DATA_KINDS, GAP_AR };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (!root || !root.document) return;

  // ====================== browser ======================
  const doc = root.document;
  const $ = (id) => doc.getElementById(id);
  const el = (tag, cls, text) => { const x = doc.createElement(tag); if (cls) x.className = cls; if (text != null) x.textContent = text; return x; };
  const state = { tab: "indices", data: {}, events: [], symbol: null, newsFilter: "important", sector: "core", sort: "latest",
    smallView: "catalysts", nasdaq: null, scroll: {} };
  const wide = () => root.matchMedia("(min-width: 1024px)").matches;

  async function load(name, file) {
    const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timer = setTimeout(() => ctrl && ctrl.abort(), 10000);
    try {
      const r = await fetch(DATA + (file || FILES[name]), { cache: "no-store", signal: ctrl ? ctrl.signal : undefined });
      if (!r.ok) throw new Error("HTTP " + r.status);
      return await r.json();
    } catch { return null; } finally { clearTimeout(timer); }
  }
  // The Nasdaq Listed directory, once; search, the catalysts tab and the detail view use it.
  let nasdaqPromise = null;
  function ensureNasdaq() {
    if (!nasdaqPromise) nasdaqPromise = load("nasdaq", NASDAQ_FILE).then((d) => {
      state.data.nasdaq = d; state.nasdaq = nasdaqMap(d);
      index = searchIndex(state.data.directory, state.events, state.nasdaq);
      return state.nasdaq;
    });
    return nasdaqPromise;
  }
  // TradingView widgets mounted only when their section is opened (they render their own data).
  function lazyEmbed(title, kind, cfg, note) {
    const d = el("details", "gr-card gr-embed"); d.append(el("summary", null, title));
    d.addEventListener("toggle", () => {
      if (!d.open || d.dataset.mounted) return;
      d.dataset.mounted = "1";
      const holder = el("div", "tradingview-widget-container"); holder.append(el("div", "tradingview-widget-container__widget"));
      const s = doc.createElement("script"); s.async = true; s.src = "https://s3.tradingview.com/external-embedding/embed-widget-" + kind + ".js";
      s.textContent = JSON.stringify(cfg);
      s.onerror = () => { holder.replaceChildren(el("p", "gr-muted", "تعذّر تحميل أداة TradingView.")); };
      holder.append(s); d.append(holder, el("p", "gr-muted", note));
    });
    return d;
  }

  // ----- watchlist (this browser only) -----
  function watchList() {
    try { const v = JSON.parse(root.localStorage.getItem(WATCH_KEY) || "[]"); return Array.isArray(v) ? v.filter((s) => SYMBOL_RE.test(s)).slice(0, 30) : []; }
    catch { return []; }
  }
  function saveWatch(list) { try { root.localStorage.setItem(WATCH_KEY, JSON.stringify(list.slice(0, 30))); } catch { /* storage blocked */ } }
  function renderWatch() {
    const list = watchList();
    $("gr-watch-count").textContent = n(list.length);
    const box = $("gr-watch-list");
    box.replaceChildren();
    if (!list.length) { box.append(el("p", "gr-muted", "لا رموز بعد. افتح سهمًا واضغط «متابعة».")); return; }
    for (const s of list) {
      const b = el("button", "gr-chip", s); b.type = "button"; b.dir = "ltr";
      b.addEventListener("click", () => openSymbol(s));
      const x = el("button", "gr-chip", "×"); x.type = "button"; x.setAttribute("aria-label", "إزالة " + s);
      x.addEventListener("click", () => { saveWatch(watchList().filter((v) => v !== s)); renderWatch(); syncWatchButton(); });
      box.append(b, x);
    }
  }
  function syncWatchButton() {
    const b = $("gr-d-watch"); if (!b || !state.symbol) return;
    const on = watchList().includes(state.symbol);
    b.setAttribute("aria-pressed", String(on)); b.textContent = on ? "★ في متابعتي" : "☆ متابعة";
  }

  // ----- summary -----
  function renderFacts() {
    const facts = $("gr-facts");
    facts.replaceChildren();
    const add = (label, value, sub) => {
      const li = el("li", "gr-fact"); li.append(el("strong", null, value)); li.append(doc.createTextNode(label + (sub ? " · " + sub : "")));
      facts.append(li);
    };
    const { plan, macro, catalysts } = state.data;
    const last = plan && plan.session ? plan.session.last_closed_session : null;
    if (last) add("آخر جلسة مكتملة", day(last));
    const curve = macro && macro.treasury_curve;
    if (curve && curve.available && curve.yields_pct && Number.isFinite(curve.yields_pct["10Y"])) {
      const sp = curve.spreads_bp && curve.spreads_bp["10Y_2Y"];
      add("عائد سندات 10 سنوات", curve.yields_pct["10Y"].toFixed(2) + "%",
        (Number.isFinite(sp) ? `الفارق مع سنتين ${signed(sp, n(Math.abs(sp)))} نقطة · ` : "") + day(curve.curve_date));
    }
    if (catalysts) {
      const week = state.events.filter((e) => e.info.group !== "admin" && Date.now() - Date.parse(e.date + "T00:00:00Z") <= 7 * 864e5);
      add("أحداث رسمية مهمة خلال 7 أيام", n(week.length), "حُدّثت " + (ago(catalysts.generated_at, Date.now()) || "—"));
    }
    if (!facts.children.length) facts.append(el("li", "gr-fact gr-muted", "ملخص السوق غير متاح الآن؛ تعذّر تحميل الملفات المنشورة."));
  }
  function renderTape() {
    const box = $("gr-tape");
    if (!box || box.dataset.mounted) return;
    box.dataset.mounted = "1";
    const holder = el("div", "tradingview-widget-container");
    holder.append(el("div", "tradingview-widget-container__widget"));
    const s = doc.createElement("script"); s.async = true; s.src = TAPE_SRC;
    s.textContent = JSON.stringify({ symbols: INDEX_ROWS.map((r) => ({ proName: `${r.symbol === "QQQ" ? "NASDAQ" : "AMEX"}:${r.symbol}`, title: r.symbol })),
      // Opaque dark theme: a transparent frame on a dark-scheme page is painted white by the browser.
      showSymbolLogo: false, colorTheme: "dark", isTransparent: false, displayMode: "compact", locale: "ar_AE" });
    s.onerror = () => { box.replaceChildren(); };
    holder.append(s); box.append(holder);
  }
  function renderSession() {
    const box = $("gr-session");
    const st = sessionState(state.data.plan, Date.now());
    box.dataset.state = st.state; box.querySelector("span").textContent = st.text;
  }

  // ----- list -----
  // A row is one button (symbol, reason, time, tags); a source link, when any, sits outside it.
  function rowEl(r, link) {
    const row = el("div", "gr-row"); row.setAttribute("role", "listitem"); row.dataset.grSymbol = r.symbol;
    const open = el("button", "gr-row-open"); open.type = "button";
    const id = el("span", "gr-row-id"); id.append(el("span", "gr-sym", r.symbol)); if (r.name) id.append(el("span", "gr-name", r.name));
    open.append(id, el("span", "gr-time", r.time || ""), el("span", "gr-why" + (r.quiet ? " gr-muted" : ""), r.why));
    const meta = el("span", "gr-meta");
    for (const t of r.tags || []) { const tag = el("span", "gr-tag", t.text); tag.dataset.kind = t.kind; meta.append(tag); }
    if (r.times) meta.append(el("span", null, r.times));
    if (meta.children.length) open.append(meta);
    open.addEventListener("click", () => openSymbol(r.symbol));
    row.append(open);
    const url = link && safeUrl(link.url);
    if (url) {
      const a = el("a", "gr-row-link", link.text + " ↗"); a.href = url; a.target = "_blank"; a.rel = "noopener";
      row.append(a);
    }
    if (state.symbol === r.symbol) row.setAttribute("aria-current", "true");
    return row;
  }
  function select(options, value, label, onChange) {
    const s = el("select"); s.setAttribute("aria-label", label);
    for (const [v, t] of options) { const o = el("option", null, t); o.value = v; if (v === value) o.selected = true; s.append(o); }
    s.addEventListener("change", () => onChange(s.value));
    return s;
  }
  function compactState(title, line, details) {
    const card = el("section", "gr-card");
    card.append(el("h2", null, title), el("p", null, line));
    if (details && details.length) {
      const d = el("details", "gr-more"); d.append(el("summary", null, "التفاصيل"));
      const ul = el("ul"); for (const t of details) ul.append(el("li", null, t)); d.append(ul); card.append(d);
    }
    return card;
  }

  const TAB_TITLES = { indices: "المؤشرات", leaders: "القياديات", small: "أسهم ذات محفزات", options: "الخيارات", news: "الأخبار" };
  function renderTab() {
    const list = $("gr-list"), tools = $("gr-list-tools"), note = $("gr-list-note"), extra = $("gr-extra");
    $("gr-list-title").textContent = TAB_TITLES[state.tab];
    for (const b of doc.querySelectorAll("[data-gr-tab]")) b.setAttribute("aria-selected", String(b.dataset.grTab === state.tab));
    $("gr-main").setAttribute("aria-labelledby", "gr-tab-" + state.tab);
    list.replaceChildren(); tools.replaceChildren(); extra.replaceChildren(); note.textContent = "";
    tools.className = "gr-list-tools";
    list.hidden = false;
    if (!state.loaded && state.tab !== "options") { list.append(el("p", "gr-empty", "جارٍ تحميل البيانات المنشورة…")); return; }
    const { catalysts, directory, macro, options } = state.data;
    let rows = [];
    if (state.tab === "indices") {
      rows = indexRows(macro);
      note.textContent = "صناديق متداولة تتتبع المؤشرات؛ المؤشر النقدي نفسه لا يظهر في أدوات TradingView المجانية.";
      const vix = el("p", "gr-muted"); vix.textContent = "VIX النقدي غير متاح في الأدوات المجانية · ";
      const a = el("a", null, "افتحه على TradingView ↗"); a.href = "https://www.tradingview.com/symbols/CBOE-VIX/"; a.target = "_blank"; a.rel = "noopener";
      vix.append(a); extra.append(vix);
    } else if (state.tab === "leaders") {
      const sectors = directory && directory.sectors ? Object.keys(directory.sectors) : [];
      const sectorAr = new Map(((directory && directory.symbols) || []).map((r) => [r.sector, r.sector_ar]));
      tools.append(select([["core", "أبرز القياديات"], ...sectors.map((s) => [s, sectorAr.get(s) || s])], state.sector, "القطاع",
        (v) => { state.sector = v; renderTab(); }));
      tools.append(select([["latest", "الأحدث حدثًا"], ["symbol", "حسب الرمز"]], state.sort, "الترتيب", (v) => { state.sort = v; renderTab(); }));
      rows = leaderRows(directory, state.events, state.sector, state.sort, catalysts);
      const c = companyCounts(directory);
      note.textContent = (directory
        ? `من قائمة أعضاء S&P 500 الحالية: ${n(c.companies)} شركة و${n(c.securities)} ورقة مالية (بعض الشركات لها أكثر من فئة أسهم)، تحديث ${day(directory.source && directory.source.data_commit_date) || "—"}.`
        : "قائمة مختصرة؛ دليل أعضاء S&P 500 لم يُنشر بعد.") +
        " S&P 500 قائمة الشركات الكبرى، وليس رادار أسهم صغيرة. الأحداث من FDA وClinicalTrials وFederal Register؛ إفصاحات SEC متوقفة حاليًا.";
      extra.append(lazyEmbed("خريطة قطاعات S&P 500 (TradingView)", "stock-heatmap", { dataSource: "SPX500", grouping: "sector",
        blockSize: "market_cap_basic", blockColor: "change", locale: "ar_AE", colorTheme: "dark", hasTopBar: false,
        isZoomEnabled: true, hasSymbolTooltip: true, isTransparent: false, width: "100%", height: 420 },
      "عرض من TradingView في متصفحك؛ لا يدخل في أي حساب لدينا."));
    } else if (state.tab === "small") {
      tools.append(select([["catalysts", "أحداث رسمية حديثة"], ["flags", "تنبيهات إدراج ناسداك"]], state.smallView, "العرض",
        (v) => { state.smallView = v; renderTab(); }));
      if (state.smallView === "flags") {
        if (!state.nasdaq) { list.append(el("p", "gr-empty", "جارٍ تحميل ملف ناسداك…")); ensureNasdaq().then(() => state.tab === "small" && renderTab()); return; }
        rows = flagRows(state.data.nasdaq);
        const nl = state.data.nasdaq;
        note.textContent = nl
          ? `من ملف «Nasdaq Listed» في NasdaqTrader (أُنشئ ${day(nl.file_created_at) || "—"}): ${n(rows.length)} سهمًا عليها تنبيه إدراج. التنبيه خطر وليس محفزًا إيجابيًا.`
          : "تعذّر تحميل ملف ناسداك.";
      } else {
        rows = smallRows(catalysts, directory, state.events);
        if (state.nasdaq) for (const r of rows) {
          const m = state.nasdaq.get(r.symbol);
          if (m && m.tier) r.tags.push({ text: m.tier, kind: "admin" });
          if (m && m.status) r.tags.unshift({ text: "⚠ تنبيه إدراج", kind: "risk" });
        } else ensureNasdaq().then(() => state.tab === "small" && state.smallView === "catalysts" && renderTab());
        note.textContent = (directory ? "شركات خارج S&P 500" : "شركات خارج قائمة الشركات الكبرى المعروفة") +
          " لديها حدث رسمي حديث. نسميها «أسهم ذات محفزات» لأن قيمتها السوقية غير موثقة (تحتاج سعرًا من مصدر يسمح بالنشر)، وليس كل حدث إيجابيًا.";
        if (!rows.length) list.append(el("p", "gr-empty", catalysts ? "لا شركات بأحداث رسمية في آخر 30 يومًا." : "تعذّر تحميل قائمة الأحداث الرسمية."));
      }
    } else if (state.tab === "options") {
      list.hidden = true;
      const reason = options && options.reason_ar ? options.reason_ar : null;
      extra.append(compactState("سلاسل الخيارات غير معروضة حاليًا",
        GAP_AR + ": جلب أسعار العقود آليًا ونشرها للعموم. لذلك لا نعرض نشاط العقود أو مستويات Gamma.",
        [...OPTION_DATA_KINDS.map(([k, v]) => `${k}: ${v}`), ...(reason ? [reason] : []), "التفاصيل الكاملة في مركز البيانات."]));
      extra.append(calculatorCard());
    } else if (state.tab === "news") {
      // Chips where they fit on one line; one dropdown on narrow screens.
      if (root.matchMedia("(min-width: 600px)").matches) {
        for (const [v, t] of FILTERS) {
          const b = el("button", "gr-chip", t); b.type = "button"; b.setAttribute("aria-pressed", String(v === state.newsFilter));
          b.addEventListener("click", () => { state.newsFilter = v; renderTab(); });
          tools.append(b);
        }
        tools.classList.add("gr-chips");
      } else tools.append(select(FILTERS, state.newsFilter, "نوع الخبر", (v) => { state.newsFilter = v; renderTab(); }));
      const src = catalysts && catalysts.sources ? catalysts.sources : {};
      if (state.newsFilter === "general") {
        const general = generalRows(state.data.fr);
        note.textContent = "إشعارات من Federal Register (الجريدة الرسمية الأمريكية) لم نربطها بسهم: الشركة خاصة أو مشروع مشترك أو مدرجة خارج أمريكا أو لم نراجع ملكيتها. لا نربط بتشابه الأسماء.";
        for (const g of general.slice(0, 80)) {
          const row = el("div", "gr-row"); row.setAttribute("role", "listitem");
          const box = el("div", "gr-row-open");
          box.append(el("span", "gr-row-id", g.agency), el("span", "gr-time", day(g.date) || ""), el("span", "gr-why", g.title));
          const meta = el("span", "gr-meta"); const tag = el("span", "gr-tag", g.label); tag.dataset.kind = "admin"; meta.append(tag);
          if (g.why) meta.append(el("span", null, g.why));
          box.append(meta); row.append(box);
          const a = el("a", "gr-row-link", "Federal Register ↗"); a.href = g.url; a.target = "_blank"; a.rel = "noopener"; row.append(a);
          list.append(row);
        }
        if (!general.length) list.append(el("p", "gr-empty", state.data.fr ? "لا إشعارات عامة في آخر 30 يومًا." : "ملف Federal Register لم يُنشر بعد."));
        return autoSelect();
      }
      const shown = filterEvents(state.events, state.newsFilter);
      note.textContent = `أحداث رسمية مرتبطة برموز: FDA${src.clinicaltrials ? " وClinicalTrials" : ""}${src.federal_register ? " وFederal Register" : ""}. ` +
        "ليس كل حدث إيجابيًا؛ تحديث السجل الإداري لا يعني نتيجة. إفصاحات SEC وأخبار علاقات المستثمرين متوقفة حتى يتوفر مصدر مسموح." +
        (catalysts ? ` آخر تحديث ${ago(catalysts.generated_at, Date.now())}.` : "");
      if (shown.length) {
        const members = directoryMap(directory);
        const dist = newsDistribution(shown, (s) => (members.get(s) || {}).sector_ar, Date.now());
        const fmt = (pairs) => pairs.slice(0, 5).map(([k, v]) => `${k} ${n(v)}`).join(" · ");
        const d = el("details", "gr-more gr-dist");
        d.append(el("summary", null, `توزيع ${n(dist.total)} خبرًا حسب المصدر: ${fmt(dist.source)}`));
        const ul = el("ul");
        ul.append(el("li", null, "النوع: " + fmt(dist.group)), el("li", null, "العمر: " + fmt(dist.age)),
          el("li", null, "القطاع (لأعضاء S&P 500): " + fmt(dist.sector)));
        d.append(ul); extra.append(d);
      }
      extra.append(lazyEmbed("التقويم الاقتصادي الأمريكي (TradingView)", "events", { colorTheme: "dark", isTransparent: false,
        width: "100%", height: 420, locale: "ar_AE", importanceFilter: "0,1", countryFilter: "us" },
      "مواعيد البيانات الاقتصادية من TradingView في متصفحك؛ لا تدخل في أي حساب لدينا."));
      for (const e of shown.slice(0, 120)) {
        list.append(rowEl({ symbol: e.symbol, name: e.issuer || "", why: eventText(e), quiet: e.info.group === "admin",
          time: day(e.date), tags: [kindTag(e)], times: timesLine(e) },
        { url: e.source_url, text: e.source || "المصدر" }));
      }
      if (!shown.length) list.append(el("p", "gr-empty", catalysts ? "لا أحداث في هذا التصنيف خلال آخر 30 يومًا." : "تعذّر تحميل الأحداث الرسمية."));
      if (shown.length > 120) extra.append(el("p", "gr-muted", `يُعرض أحدث 120 من ${n(shown.length)} حدثًا.`));
      return autoSelect();
    }
    for (const r of rows) list.append(rowEl(r));
    if (!rows.length && !list.hidden && !list.children.length) list.append(el("p", "gr-empty", "لا عناصر لعرضها."));
    autoSelect();
  }
  // Wide screens always show a chart: the first row, only while nothing is
  // selected (a symbol from a link, the search or a click is never replaced).
  function autoSelect() {
    if (!wide() || state.symbol) return;
    const first = doc.querySelector("#gr-list [data-gr-symbol]");
    openSymbol(first ? first.dataset.grSymbol : "SPY", { push: false });
  }
  // The tab a linked symbol belongs to.
  function tabFor(symbol) {
    if (INDEX_ROWS.some((r) => r.symbol === symbol)) return "indices";
    const members = directoryMap(state.data.directory);
    if (members.has(symbol) || CORE_LEADERS.includes(symbol) || largeOutside(state.data.catalysts, members).has(symbol)) return "leaders";
    if (smallRows(state.data.catalysts, state.data.directory, state.events).some((r) => r.symbol === symbol)) return "small";
    if (state.events.some((e) => e.symbol === symbol)) return "news";
    return "leaders";
  }

  function calculatorCard() {
    const card = el("section", "gr-card");
    card.append(el("h2", null, "حاسبة العقد عند الانتهاء"),
      el("p", null, "أدخل أرقام العقد من منصتك. لا تستخدم بيانات سوق، ولا تشمل القيمة الزمنية قبل الانتهاء أو العمولات."));
    const form = el("form", "gr-form");
    const field = (label, input) => { const l = el("label", null, label); l.append(input); form.append(l); return input; };
    const type = field("نوع العقد", select([["CALL", "CALL (حق الشراء)"], ["PUT", "PUT (حق البيع)"]], "CALL", "نوع العقد", () => calc()));
    const num = (ph) => { const i = el("input"); i.type = "number"; i.step = "any"; i.min = "0"; i.inputMode = "decimal"; i.placeholder = ph; i.dir = "ltr"; return i; };
    const strike = field("سعر التنفيذ", num("مثال 200")), premium = field("سعر العقد للسهم", num("مثال 3.5"));
    const contracts = field("عدد العقود", num("1")), spot = field("سعر السهم الآن (اختياري)", num("مثال 195"));
    const out = el("p", "gr-result", "النتيجة تظهر هنا."); out.setAttribute("role", "status");
    function calc() {
      const r = optionMath({ type: type.value, strike: strike.value, premium: premium.value, contracts: contracts.value, spot: spot.value });
      if (!r) { out.textContent = "أدخل سعر التنفيذ وسعر العقد."; return; }
      out.textContent = `نقطة التعادل عند الانتهاء: ${n(r.breakeven)} · أقصى خسارة: ${n(r.max_loss)} دولار` +
        (r.move_pct != null ? ` · يحتاج السهم حركة ${r.move_pct >= 0 ? "▲" : "▼"} ${signed(r.move_pct, n(Math.abs(r.move_pct)) + "%")} حتى التعادل` : "");
    }
    for (const i of [strike, premium, contracts, spot]) i.addEventListener("input", calc);
    form.addEventListener("submit", (e) => { e.preventDefault(); calc(); });
    card.append(form, out);
    return card;
  }

  // ----- detail -----
  function tvLink(info, symbol) {
    if (info && info.cash_url && info.kind === "UNAVAILABLE") return info.cash_url;
    const tv = info && info.tv ? info.tv.replace(":", "-") : symbol;
    return "https://www.tradingview.com/symbols/" + encodeURIComponent(tv) + "/";
  }
  let chartTimer = null, chartObserver = null;
  function mountChart(symbol, interval) {
    const box = doc.querySelector("[data-gr-chart]");
    const slot = box.querySelector(".gr-chart-slot"), stateBox = box.querySelector(".gr-chart-state"), note = box.querySelector(".gr-chart-note");
    clearTimeout(chartTimer); if (chartObserver) chartObserver.disconnect();
    const TV = root.GhaziTV;
    const info = TV ? TV.resolve(symbol) : null;
    const link = tvLink(info, symbol);
    box.dataset.symbol = symbol;
    const external = () => { const a = el("a", null, "افتح الشارت على TradingView ↗"); a.href = link; a.target = "_blank"; a.rel = "noopener"; return a; };
    const setState = (s, text, withRetry) => {
      box.dataset.state = s; stateBox.replaceChildren();
      if (text) stateBox.append(el("span", null, text + " "));
      if (withRetry) { const b = el("button", null, "إعادة المحاولة"); b.type = "button"; b.addEventListener("click", () => mountChart(symbol, interval)); stateBox.append(b, doc.createTextNode(" ")); }
      if (s !== "loading") stateBox.append(external());
    };
    note.textContent = info ? info.note_ar + " نرصد تحميل إطار الشارت فقط؛ المتصفح لا يسمح بقراءة محتواه، فرسائل مثل «الرمز غير موجود» تأتي من TradingView." : "";
    slot.replaceChildren();
    if (!TV || !info) { setState("failed", "أداة الشارت لم تُحمّل."); return; }
    if (info.kind === "UNAVAILABLE") { setState("unavailable", info.note_ar); return; }
    const cfg = TV.config("advanced-chart", symbol, interval);
    if (!cfg) { setState("failed", "تعذّر تجهيز الشارت لهذا الرمز."); return; }
    setState("loading", "جارٍ تحميل الشارت…");
    const holder = el("div", "tradingview-widget-container"); holder.style.height = "100%";
    const inner = el("div", "tradingview-widget-container__widget"); inner.style.height = "100%";
    const script = doc.createElement("script"); script.async = true; script.src = TV.widgetSrc("advanced-chart");
    script.textContent = JSON.stringify(cfg);
    script.onerror = () => { clearTimeout(chartTimer); setState("failed", "تعذّر تحميل أداة TradingView (حجب شبكة أو إضافة متصفح)."); };
    holder.append(inner, script); slot.append(holder);
    // What can be observed from outside a cross-origin frame: that it was created and that it loaded.
    const watchFrame = (frame) => frame.addEventListener("load", () => { clearTimeout(chartTimer); setState("ready", ""); }, { once: true });
    chartObserver = new MutationObserver(() => { const f = slot.querySelector("iframe"); if (f) { chartObserver.disconnect(); watchFrame(f); } });
    chartObserver.observe(slot, { childList: true, subtree: true });
    chartTimer = setTimeout(() => { if (box.dataset.state === "loading") setState("timeout", `لم يكتمل تحميل الشارت خلال ${CHART_TIMEOUT_MS / 1000} ثانية.`, true); }, CHART_TIMEOUT_MS);
  }
  function chartBar(symbol) {
    const bar = doc.querySelector("[data-gr-chart] .gr-chart-bar");
    bar.replaceChildren();
    const frames = [["15", "15د"], ["60", "ساعة"], ["240", "4س"], ["D", "يومي"], ["W", "أسبوعي"]];
    for (const [v, t] of frames) {
      const b = el("button", null, t); b.type = "button"; b.dataset.interval = v; b.setAttribute("aria-pressed", String(v === "D"));
      b.addEventListener("click", () => { for (const x of bar.children) x.setAttribute("aria-pressed", String(x === b)); mountChart(symbol, v); });
      bar.append(b);
    }
  }
  function section(title) { const s = el("section", "gr-card"); s.append(el("h3", null, title)); return s; }
  function renderDetailBody(symbol) {
    const body = $("gr-d-body"); body.replaceChildren();
    const { directory, macro, catalysts } = state.data;
    const member = directoryMap(directory).get(symbol);
    const index = INDEX_ROWS.find((r) => r.symbol === symbol);
    const mine = state.events.filter((e) => e.symbol === symbol);
    const top = headline(mine);
    const listed = state.nasdaq ? state.nasdaq.get(symbol) : null;
    // A name is shown only from a list that holds the symbol; never guessed.
    $("gr-d-name").textContent = (member && member.name) || (index && index.name) || (listed && listed.name) ||
      (top && top.issuer) || FALLBACK_NAMES[symbol] || "";

    // Why it is here
    const why = section("لماذا يظهر");
    const reasons = el("ul", "gr-d-list");
    if (index) reasons.append(el("li", null, index.name + "؛ يُعرض بدل المؤشر النقدي غير المتاح في الأدوات المجانية."));
    if (member) reasons.append(el("li", null, `عضو في S&P 500 · ${member.sector_ar}${member.sub_industry ? " · " + member.sub_industry : ""}`));
    else if (CORE_LEADERS.includes(symbol)) reasons.append(el("li", null, "ضمن قائمة القياديات المختصرة في الموقع."));
    if (listed) reasons.append(el("li", null, `مدرج في ناسداك · ${listed.tier || "فئة غير محددة"}${listed.security ? " · " + listed.security : ""}${listed.etf ? " · صندوق متداول" : ""} (ملف NasdaqTrader)`));
    if (listed && listed.status) {
      const li = el("li"); const tag = el("span", "gr-tag", "⚠ تنبيه إدراج"); tag.dataset.kind = "risk";
      li.append(tag, doc.createTextNode(" " + (STATUS_AR[listed.status] || listed.status) + " — حسب ملف ناسداك؛ خطر وليس محفزًا.")); reasons.append(li);
    }
    if (top) reasons.append(el("li", null, `${top.info.label}: ${eventText(top)} (${day(top.date)})`));
    if (!reasons.children.length) reasons.append(el("li", null, state.nasdaq
      ? "رمز من بحثك غير موجود في قوائمنا (S&P 500 وملف ناسداك)؛ قد يكون مدرجًا في بورصة أخرى. لم نتحقق من اسم الشركة أو بورصتها."
      : "رمز من بحثك؛ لم نتحقق بعد من اسم الشركة أو بورصتها."));
    why.append(reasons); body.append(why);
    if (!member && !index && !state.nasdaq) ensureNasdaq().then(() => state.symbol === symbol && state.nasdaq.size && renderDetailBody(symbol));

    // Index context: published CFTC positions
    if (index) {
      const c = macro && macro.cftc_index_futures && macro.cftc_index_futures[index.cftc];
      const s = section("مراكز العقود الآجلة (CFTC)");
      if (c && c.available && c.categories) {
        const kv = el("div", "gr-kv");
        const labels = { asset_manager: "مديرو الأصول", leveraged_funds: "الصناديق ذات الرافعة", dealer: "الوسطاء" };
        for (const [k, label] of Object.entries(labels)) {
          const v = c.categories[k]; if (!v || !Number.isFinite(v.net)) continue;
          const d = el("div"); d.append(el("b", null, `${v.net >= 0 ? "صافي شراء" : "صافي بيع"} ${compact(Math.abs(v.net))}`));
          d.append(doc.createTextNode(label + (Number.isFinite(v.weekly_change) ? ` · أسبوعيًا ${v.weekly_change >= 0 ? "▲" : "▼"} ${signed(v.weekly_change, compact(Math.abs(v.weekly_change)))}` : "")));
          kv.append(d);
        }
        s.append(kv, el("p", "gr-muted", `${c.label_ar || c.market} · مراكز ${day(c.positions_as_of)} · تقرير أسبوعي، وليس تدفقًا لحظيًا ولا اتجاهًا.`));
      } else s.append(el("p", null, "غير منشورة في آخر تقرير."));
      body.append(s);
    }

    // News and disclosures for this symbol
    const news = section("الأخبار والإفصاحات");
    if (mine.length) {
      const ul = el("ul", "gr-d-list");
      for (const e of mine.slice(0, 12)) {
        const li = el("li"); li.append(el("p", null, eventText(e)));
        const meta = el("span", "gr-meta"); const kt = kindTag(e); const tag = el("span", "gr-tag", kt.text); tag.dataset.kind = kt.kind;
        meta.append(tag, el("span", null, timesLine(e)));
        const url = safeUrl(e.source_url);
        if (url) { const a = el("a", null, (e.source || "المصدر") + " ↗"); a.href = url; a.target = "_blank"; a.rel = "noopener"; meta.append(a); }
        li.append(meta); ul.append(li);
      }
      news.append(ul);
    } else news.append(el("p", null, !state.loaded ? "جارٍ التحميل…" : catalysts
      ? "لا أحداث رسمية لهذا الرمز في مصادرنا خلال 30 يومًا (FDA وClinicalTrials وFederal Register)." : "تعذّر تحميل الأحداث الرسمية."));
    if (!index) {
      const sec = el("p", "gr-muted");
      const a = el("a", null, "إفصاحات الشركة على SEC EDGAR ↗");
      a.href = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&owner=include&count=40&CIK=" +
        encodeURIComponent(member ? member.cik : symbol);
      a.target = "_blank"; a.rel = "noopener";
      sec.append(a, doc.createTextNode(" · جلبنا الآلي من SEC متوقف (يرفض المزود الطلب حتى نضيف هوية تعريف)."));
      news.append(sec);
    }
    body.append(news);

    // Price analysis: one honest line, no empty level boxes
    const price = section("التحليل السعري");
    price.append(el("p", null, `غير متاح: ${GAP_AR} (شموع أسعار تسمح بحساب المستويات ونشرها). الشارت أعلاه عرض من TradingView ولا يدخل في أي حساب.`));
    body.append(price);
  }
  let returnFocus = null;
  function openSymbol(symbol, opts = {}) {
    const s = String(symbol || "").trim().toUpperCase();
    if (!SYMBOL_RE.test(s)) return;
    state.symbol = s;
    const from = doc.activeElement;
    if (from && from !== doc.body && !$("gr-detail").contains(from)) returnFocus = from;
    const panel = $("gr-detail");
    $("gr-d-symbol").textContent = s;
    for (const r of doc.querySelectorAll("#gr-list .gr-row")) {
      if (r.dataset.grSymbol === s) r.setAttribute("aria-current", "true"); else r.removeAttribute("aria-current");
    }
    chartBar(s); mountChart(s, "D"); renderDetailBody(s); syncWatchButton();
    panel.classList.add("is-open");
    if (!wide()) { doc.body.style.overflow = "hidden"; panel.scrollTop = 0; panel.focus({ preventScroll: true }); }
    if (opts.push !== false) {
      const url = new URL(root.location.href); url.searchParams.set("tab", state.tab); url.searchParams.set("s", s); url.searchParams.delete("chart");
      root.history.pushState({ s, tab: state.tab }, "", url);
    }
  }
  // Closing returns to the same place in the list: the page scroll is untouched and
  // focus goes back to the row or search box that opened the stock.
  function closeDetail() {
    $("gr-detail").classList.remove("is-open"); doc.body.style.overflow = "";
    if (returnFocus && doc.contains(returnFocus)) returnFocus.focus({ preventScroll: true });
  }

  // ----- search -----
  let index = [];
  function wireSearch() {
    const input = $("gr-q"), box = $("gr-suggest");
    let items = [], active = -1;
    const close = () => { box.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
    const paint = () => {
      box.replaceChildren();
      items.forEach((it, i) => {
        const li = el("li"); li.id = "gr-sg-" + i; li.setAttribute("role", "option"); li.setAttribute("aria-selected", String(i === active));
        li.append(el("b", null, it.symbol), el("small", null, [it.name, it.sector].filter(Boolean).join(" · ")));
        li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(it.symbol); });
        box.append(li);
      });
      box.hidden = !items.length; input.setAttribute("aria-expanded", String(!!items.length));
      if (active >= 0) input.setAttribute("aria-activedescendant", "gr-sg-" + active); else input.removeAttribute("aria-activedescendant");
    };
    const choose = (s) => { input.value = ""; close(); openSymbol(s); };
    const refresh = () => { items = suggest(index, input.value); active = -1; paint(); };
    // The Nasdaq directory joins the search on first use; suggestions refresh when it arrives.
    input.addEventListener("focus", () => { if (!state.nasdaq) ensureNasdaq().then(() => { if (doc.activeElement === input && input.value) refresh(); }); });
    input.addEventListener("input", refresh);
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" && items.length) { active = (active + 1) % items.length; paint(); e.preventDefault(); }
      else if (e.key === "ArrowUp" && items.length) { active = (active - 1 + items.length) % items.length; paint(); e.preventDefault(); }
      else if (e.key === "Escape") close();
    });
    input.addEventListener("blur", () => setTimeout(close, 120));
    $("gr-search").addEventListener("submit", (e) => {
      e.preventDefault();
      const pick = active >= 0 ? items[active] : suggest(index, input.value, 1)[0];
      const typed = String(input.value || "").trim().toUpperCase();
      // A suggestion picked with the arrows wins; otherwise a valid symbol outside every list
      // opens as typed (marked unverified) rather than the nearest name.
      if (active >= 0) choose(items[active].symbol);
      else if (SYMBOL_RE.test(typed) && (!pick || pick.symbol !== typed) && index.every((it) => it.symbol !== typed)) choose(typed);
      else if (pick) choose(pick.symbol); else if (SYMBOL_RE.test(typed)) choose(typed);
    });
  }

  // Each tab keeps its own scroll position.
  function setTab(tab, push) {
    if (!TAB_TITLES[tab]) return;
    state.scroll[state.tab] = root.scrollY;
    state.tab = tab; renderTab();
    root.scrollTo(0, state.scroll[tab] || 0);
    if (push) { const url = new URL(root.location.href); url.searchParams.set("tab", tab); root.history.replaceState(root.history.state, "", url); }
  }

  async function start() {
    // Back/forward only open or close the stock view; the browser must not move the list.
    if ("scrollRestoration" in root.history) root.history.scrollRestoration = "manual";
    renderWatch();
    const params = new URLSearchParams(root.location.search);
    const linked = String(params.get("s") || params.get("chart") || "").toUpperCase();
    const tab = params.get("tab");
    if (TAB_TITLES[tab]) state.tab = tab;
    else if (linked && !INDEX_ROWS.some((r) => r.symbol === linked)) state.tab = "leaders";
    for (const b of doc.querySelectorAll("[data-gr-tab]")) b.addEventListener("click", () => setTab(b.dataset.grTab, true));
    $("gr-watch-btn").addEventListener("click", () => {
      const p = $("gr-watch-panel"); p.hidden = !p.hidden; $("gr-watch-btn").setAttribute("aria-expanded", String(!p.hidden));
    });
    $("gr-d-watch").addEventListener("click", () => {
      const list = watchList(); const s = state.symbol; if (!s) return;
      saveWatch(list.includes(s) ? list.filter((v) => v !== s) : [...list, s]); renderWatch(); syncWatchButton();
    });
    $("gr-d-back").addEventListener("click", () => { if (root.history.state && root.history.state.s) root.history.back(); else closeDetail(); });
    root.addEventListener("popstate", (e) => {
      const s = e.state && e.state.s;
      if (s) openSymbol(s, { push: false }); else if (!wide()) closeDetail();
    });
    root.addEventListener("keydown", (e) => { if (e.key === "Escape" && !wide() && $("gr-detail").classList.contains("is-open")) $("gr-d-back").click(); });
    wireSearch();
    renderSession(); setInterval(renderSession, 60000);
    renderTab();
    if (linked && SYMBOL_RE.test(linked)) openSymbol(linked, { push: false });
    const names = Object.keys(FILES);
    const loaded = await Promise.all(names.map((k) => load(k)));
    names.forEach((k, i) => { state.data[k] = loaded[i]; });
    state.loaded = true;
    state.events = eventRows(state.data.catalysts);
    index = searchIndex(state.data.directory, state.events);
    if (linked && SYMBOL_RE.test(linked) && !TAB_TITLES[tab]) state.tab = tabFor(linked);
    renderSession(); renderFacts(); renderTab(); renderTape();
    if (state.symbol) renderDetailBody(state.symbol);
  }
  if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start); else start();
})(typeof window !== "undefined" ? window : null);
