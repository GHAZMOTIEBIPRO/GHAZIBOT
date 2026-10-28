// One-time look at public reference sites for information organisation (UX research only).
//
// Opens each page once per viewport after checking robots.txt for "/" (or the
// page path), and prints its structure: title, language/direction, navigation
// labels, headings, counts of tables/charts/iframes, fixed bottom bars, fonts
// and colours. Nothing is stored in the repository; no content is republished.
"use strict";
const { chromium } = require("playwright");

const SITES = [
  "https://oxchart.sa/", "https://mrchart.com/", "https://mrwallstreets.com/", "https://options.chartxpert.io/ar",
  "https://obitrade2030.com/", "https://finviz.com/", "https://optionstrat.com/", "https://unusualwhales.com/",
  "https://spotgamma.com/", "https://marketchameleon.com/", "https://www.barchart.com/options",
  "https://stockanalysis.com/", "https://www.tradingview.com/widget-docs/", "https://www.koyfin.com/features/",
  "https://trendspider.com/", "https://updates.smartincome-17.com/",
];
const UA = "Mozilla/5.0 (compatible; GHAZI-RADAR-ux-review/1.0; one-time design review)";

async function robotsAllows(url) {
  const u = new URL(url);
  try {
    const r = await fetch(`${u.origin}/robots.txt`, { headers: { "User-Agent": UA }, signal: AbortSignal.timeout(10000) });
    if (!r.ok) return { allowed: true, robots: `HTTP ${r.status}` };
    const lines = (await r.text()).split(/\r?\n/).map((l) => l.replace(/#.*/, "").trim());
    let applies = false;
    const disallow = [];
    for (const l of lines) {
      const [k, ...rest] = l.split(":");
      const v = rest.join(":").trim();
      if (/^user-agent$/i.test(k)) applies = v === "*";
      else if (applies && /^disallow$/i.test(k) && v) disallow.push(v);
    }
    const path = u.pathname || "/";
    const blocked = disallow.find((d) => d === "/" || path.startsWith(d));
    return { allowed: !blocked, robots: blocked ? `Disallow: ${blocked}` : "ok" };
  } catch (e) {
    return { allowed: true, robots: "unreachable: " + String(e.message).slice(0, 60) };
  }
}

function outline() {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
  const txt = (el) => (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 60);
  const uniq = (a) => [...new Set(a.filter(Boolean))];
  const navs = uniq([...document.querySelectorAll("nav a, header a, [role=navigation] a, [role=tab]")]
    .filter(vis).map(txt)).slice(0, 40);
  const heads = uniq([...document.querySelectorAll("h1,h2,h3")].filter(vis).map((h) => h.tagName + ": " + txt(h))).slice(0, 30);
  const fixedBottom = [...document.querySelectorAll("body *")].filter((el) => {
    const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    return (s.position === "fixed" || s.position === "sticky") && r.bottom >= innerHeight - 2 && r.height < 120 && r.width > innerWidth * 0.6;
  }).slice(0, 2).map((el) => ({ items: [...el.querySelectorAll("a,button")].filter(vis).map(txt).slice(0, 8), height: Math.round(el.getBoundingClientRect().height) }));
  const fixedTop = [...document.querySelectorAll("body *")].some((el) => {
    const s = getComputedStyle(el); const r = el.getBoundingClientRect();
    return (s.position === "fixed" || s.position === "sticky") && r.top <= 1 && r.height < 140 && r.width > innerWidth * 0.6;
  });
  const bs = getComputedStyle(document.body);
  return {
    title: document.title.slice(0, 90), lang: document.documentElement.lang, dir: document.documentElement.dir || bs.direction,
    nav: navs, headings: heads,
    counts: { tables: document.querySelectorAll("table").length, canvas: document.querySelectorAll("canvas").length,
      svg: document.querySelectorAll("svg").length, iframes: document.querySelectorAll("iframe").length,
      inputs: document.querySelectorAll("input,select").length, buttons: document.querySelectorAll("button").length },
    sticky_top_bar: fixedTop, bottom_bars: fixedBottom,
    font: bs.fontFamily.slice(0, 80), font_size: bs.fontSize, bg: bs.backgroundColor, color: bs.color,
    page_height: document.documentElement.scrollHeight,
  };
}

(async () => {
  const browser = await chromium.launch();
  for (const url of SITES) {
    const rb = await robotsAllows(url);
    if (!rb.allowed) { console.log("REF", JSON.stringify({ url, skipped: "robots.txt", robots: rb.robots })); continue; }
    const out = { url, robots: rb.robots };
    for (const [name, vp] of [["desktop", { width: 1366, height: 900 }], ["phone", { width: 390, height: 844 }]]) {
      const ctx = await browser.newContext({ viewport: vp, userAgent: UA, isMobile: name === "phone", hasTouch: name === "phone" });
      const page = await ctx.newPage();
      try {
        const resp = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
        await page.waitForTimeout(4000);
        out[name] = { http: resp ? resp.status() : null, ...(await page.evaluate(outline)) };
      } catch (e) {
        out[name] = { error: String(e.message).split("\n")[0].slice(0, 120) };
      }
      await ctx.close();
    }
    console.log("REF", JSON.stringify(out));
  }
  await browser.close();
})();
