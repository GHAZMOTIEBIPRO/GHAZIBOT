import crypto from "node:crypto";

export const BLOCK_RX = /(captcha|verify you are human|access denied|forbidden|cloudflare|robot check)/i;
export const OOS_RX = /(out of stock|sold out|currently unavailable|notify me when available|notify when available|back in stock|غير متوفر|نفدت الكمية|غير متاح|أخبرني عند التوفر|اخبرني عند التوفر|أعلمني عند التوفر|اعلمني عند التوفر|نبهني عند التوفر)/i;
export const IN_STOCK_RX = /(in stock|add to cart|add to bag|أضف للسلة|اضف للسلة|متوفر)/i;
export const SAUDI_SHIP_RX = /(saudi arabia|kingdom of saudi arabia|ksa|السعودية|المملكة العربية السعودية)/i;

export function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

export function cleanText(s="") {
  return String(s).replace(/<[^>]*>/g, " ").replace(/&nbsp;/gi," ")
    .replace(/&amp;/gi,"&").replace(/\s+/g," ").trim();
}

export function normalizeUrl(input, base) {
  try {
    const u = new URL(input, base);
    if (!["http:","https:"].includes(u.protocol)) return null;
    const remove = [];
    u.searchParams.forEach((_v,k)=>{
      if (/^(utm_|gclid|fbclid|ref$|affiliate|aff_)/i.test(k)) remove.push(k);
    });
    remove.forEach(k=>u.searchParams.delete(k));
    u.hash = "";
    return u.toString();
  } catch { return null; }
}

export function sameHostOrChild(a,b) {
  try {
    const ah = new URL(a).hostname.replace(/^www\./,"");
    const bh = new URL(b).hostname.replace(/^www\./,"");
    return ah === bh || ah.endsWith("." + bh) || bh.endsWith("." + ah);
  } catch { return false; }
}

export function hash(s) {
  return crypto.createHash("sha256").update(String(s)).digest("hex");
}

export function parseNumber(v) {
  if (v == null) return null;
  const s = String(v)
    .replace(/[٬,](?=\d{3}\b)/g,"")
    .replace(/[^\d.,-]/g,"")
    .replace(",",".");
  const n = Number(s);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export function pct(current, previous) {
  if (!(current > 0) || !(previous > current)) return null;
  return Math.round(((previous-current)/previous)*1000)/10;
}

export function priceTruth(p, historyStats) {
  const current = Number(p.currentPrice || 0);
  if (!(current > 0)) return { verified:false, percent:null, type:"none", reference:null };
  if (historyStats?.d30?.samples >= 3 && historyStats.d30.median > current) {
    return {verified:true,percent:pct(current, historyStats.d30.median),type:"historical_30d_median",reference:historyStats.d30.median};
  }
  if (p.previousPrice && p.previousPrice > current) {
    return {verified:true,percent:pct(current,p.previousPrice),type:"store_previous_price",reference:p.previousPrice};
  }
  if (p.rrp && p.rrp > current) return { verified:false, percent:null, type:"rrp_only", reference:p.rrp };
  if (p.msrp && p.msrp > current) return { verified:false, percent:null, type:"msrp_only", reference:p.msrp };
  return { verified:false, percent:null, type:"none", reference:null };
}

function med(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a,b)=>a-b);
  const m = Math.floor(s.length/2);
  return s.length%2 ? s[m] : Math.round(((s[m-1]+s[m])/2)*100)/100;
}

export function windowStats(points, days, now=Date.now()) {
  const cutoff = now - days*86400000;
  const pts = points.filter(x => x.t >= cutoff && x.price > 0).sort((a,b)=>a.t-b.t);
  if (!pts.length) return {days,samples:0,min:null,max:null,average:null,median:null,current:null,isLowest:false};
  const prices = pts.map(x=>x.price);
  const current = pts.at(-1).price;
  const min = Math.min(...prices), max = Math.max(...prices);
  return {days,samples:pts.length,min,max,average:Math.round((prices.reduce((a,b)=>a+b,0)/prices.length)*100)/100,median:med(prices),current,isLowest:current <= min};
}

export function historyWindows(points, now=Date.now()) {
  return {d7:windowStats(points,7,now),d30:windowStats(points,30,now),d90:windowStats(points,90,now)};
}

export function dealScore(x) {
  if (x.availability !== "in_stock") return 0;
  if (!["confirmed","local_context"].includes(x.shipping)) return 0;
  let s = 0;
  const d = Math.max(0,Math.min(90,x.discountPercent||0));
  s += Math.min(42,d*0.58);
  if (x.evidenceType === "historical_30d_median") s += 18;
  else if (x.evidenceType === "store_previous_price") s += 12;
  if (x.lowest30) s += 12;
  if (x.lowest90) s += 8;
  if (x.outlet) s += 5;
  s += Math.max(0,Math.min(10,(x.sourceReliability||0)*10));
  if (x.ageMinutes <= 30) s += 5;
  else if (x.ageMinutes <= 180) s += 3;
  return Math.round(Math.max(0,Math.min(100,s)));
}

function decodeHtmlAttr(s="") {
  return String(s).replace(/&amp;/gi,"&").replace(/&quot;/gi,'"').replace(/&#39;|&apos;/gi,"'").replace(/&lt;/gi,"<").replace(/&gt;/gi,">");
}

function normalizeImageUrl(input,base){
  try{
    const raw=decodeHtmlAttr(input).trim();
    if(!raw || /^data:/i.test(raw)) return null;
    const u=new URL(raw,base);
    if(!["http:","https:"].includes(u.protocol)) return null;
    return u.toString();
  }catch{return null}
}

export function extractBestImage(html,pageUrl,title="") {
  const body=String(html||""), candidates=[];
  const add=(raw,score=0)=>{const url=normalizeImageUrl(raw,pageUrl);if(!url)return;if(/(?:logo|icon|sprite|placeholder|spinner|loader|badge|payment|tabby|tamara|flag|\.svg(?:$|\?))/i.test(url))score-=80;if(/(?:product|products|gallery|zoom|large|original|media|catalog|image)/i.test(url))score+=12;candidates.push({url,score})};
  for(const m of body.matchAll(/<meta\b[^>]*(?:property|name)=["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["'][^>]*content=["']([^"']+)["'][^>]*>/gi))add(m[1],100);
  for(const m of body.matchAll(/<meta\b[^>]*content=["']([^"']+)["'][^>]*(?:property|name)=["'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["'][^>]*>/gi))add(m[1],100);
  for(const m of body.matchAll(/<link\b[^>]*rel=["']image_src["'][^>]*href=["']([^"']+)["'][^>]*>/gi))add(m[1],90);
  const titleWords=cleanText(title).toLowerCase().split(/\s+/).filter(w=>w.length>3).slice(0,5);
  for(const m of body.matchAll(/<img\b([^>]+)>/gi)){
    const attrs=m[1], src=(attrs.match(/(?:src|data-src|data-lazy-src|data-original)=["']([^"']+)["']/i)||[])[1];if(!src)continue;
    const alt=cleanText((attrs.match(/alt=["']([^"']*)["']/i)||[])[1]||"").toLowerCase();
    let score=20;if(/gallery|product|pdp|main|zoom|hero/i.test(attrs))score+=35;if(titleWords.some(w=>alt.includes(w)))score+=25;if(/thumb/i.test(attrs))score-=8;add(src,score);
  }
  candidates.sort((a,b)=>b.score-a.score);return candidates[0]?.url||null;
}

export function extractJsonLdProducts(html, sourceKey, sourcePageUrl) {
  const blocks = [...html.matchAll(/<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)];
  const products = [];
  const walk = (node) => {
    if (!node) return;
    if (Array.isArray(node)) return node.forEach(walk);
    if (typeof node !== "object") return;
    const types = Array.isArray(node["@type"]) ? node["@type"] : [node["@type"]];
    if (types.map(String).some(t=>t.toLowerCase()==="product")) products.push(node);
    if (node["@graph"]) walk(node["@graph"]);
  };
  for (const m of blocks) { try { walk(JSON.parse(m[1].trim())); } catch {} }
  const out = [];
  for (const p of products) {
    const offers = Array.isArray(p.offers) ? p.offers : p.offers ? [p.offers] : [];
    const offer = offers[0] || {};
    const currentPrice = parseNumber(offer.price ?? offer.lowPrice);
    const url = normalizeUrl(p.url || offer.url || "", sourcePageUrl);
    if (!p.name || !url || !currentPrice) continue;
    const av = String(offer.availability||"").toLowerCase();
    const priceSpec=Array.isArray(offer.priceSpecification)?offer.priceSpecification[0]:offer.priceSpecification||{};
    const previousPrice=parseNumber(offer.highPrice ?? offer.listPrice ?? offer.regularPrice ?? priceSpec?.maxPrice ?? priceSpec?.listPrice ?? priceSpec?.regularPrice);
    const declaredImage=Array.isArray(p.image) ? p.image[0] : p.image || null;
    out.push({sourceKey, sourcePageUrl,title:cleanText(p.name),productUrl:url,imageUrl:normalizeImageUrl(declaredImage,sourcePageUrl) || extractBestImage(html,sourcePageUrl,p.name),currentPrice,previousPrice:previousPrice && previousPrice>currentPrice ? previousPrice : null,currency:offer.priceCurrency || "SAR",availability:av.includes("instock") ? "in_stock" : av.includes("outofstock") ? "out_of_stock" : "unknown",sku:p.sku || null,brand:typeof p.brand==="string" ? p.brand : p.brand?.name || null,category:p.category || null,metadata:{jsonLd:true}});
  }
  return out;
}

export function discoverProductLinks(html, pageUrl, max=40) {
  const links = [], seen = new Set();
  for (const m of html.matchAll(/<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
    const url = normalizeUrl(m[1], pageUrl);
    if (!url || !sameHostOrChild(url,pageUrl) || seen.has(url)) continue;
    const label = cleanText(m[2]);
    if (!label || label.length < 3) continue;
    if (/(\/p\/|\/product|\/products\/|\.html(?:\?|$)|-p-\d+|\/item\/)/i.test(new URL(url).pathname + new URL(url).search)) {seen.add(url);links.push({url,label});if (links.length >= max) break;}
  }
  return links;
}

export function inferAvailability(html, declared="unknown") {
  if (declared === "out_of_stock") return "out_of_stock";
  const body=String(html||"");
  const oosIndex=body.search(OOS_RX), inIndex=body.search(IN_STOCK_RX);
  if (oosIndex >= 0 && (inIndex < 0 || oosIndex < inIndex)) return "out_of_stock";
  if (declared === "in_stock") return "in_stock";
  if (inIndex >= 0) return "in_stock";
  return "unknown";
}

export function inferShipping(source, html) {
  const f = source.saudiFulfillment;
  if (["local","sa_storefront"].includes(f) || source.countryScope === "SA") return "local_context";
  if (["SA_storefront","SA_or_SA_storefront"].includes(source.countryScope)) return "local_context";
  if (f === "international_to_sa" && SAUDI_SHIP_RX.test(html)) return "confirmed";
  return "unknown";
}

export function extractPreviousPriceFromText(html, current) {
  const text = cleanText(html), raw=String(html||""), candidates = [];
  const push=n=>{n=parseNumber(n);if(n&&n>current&&n<current*10)candidates.push(n)};
  const patterns = [/(?:was|before|old price|previous price|regular price|original price|list price|السعر السابق|السعر قبل|قبل)\s*[:\-]?\s*(?:SAR|ر\.?س\.?|ريال)?\s*([\d,.]+)/ig,/(?:SAR|ر\.?س\.?|ريال)\s*([\d,.]+)\s*(?:was|before|السابق|قبل)/ig];
  for (const rx of patterns) for (const m of text.matchAll(rx)) push(m[1]);
  for(const m of raw.matchAll(/"(?:oldPrice|originalPrice|regularPrice|compareAtPrice|compare_at_price|wasPrice|previousPrice|listPrice|priceBeforeDiscount|highPrice)"\s*:\s*"?([\d.,]+)"?/gi))push(m[1]);
  for(const m of raw.matchAll(/<(?:del|s)\b[^>]*>\s*(?:SAR|ر\.?س\.?|ريال)?\s*([\d,.]+)/gi))push(m[1]);
  for(const m of raw.matchAll(/<(?:span|div|p)\b[^>]*(?:class|id)=["'][^"']*(?:old|was|regular|original|compare|list|previous|before|strike)[^"']*["'][^>]*>[\s\S]{0,120}?([\d,.]+)/gi))push(m[1]);
  return candidates.length ? Math.min(...candidates) : null;
}

export async function fetchPage(url, {timeoutMs=15000,maxBytes=1800000}={}) {
  const ctl = new AbortController();
  const timer = setTimeout(()=>ctl.abort(),timeoutMs);
  try {
    const res = await fetch(url,{redirect:"follow",signal:ctl.signal,headers:{"user-agent":"RadarDealsSaudi/Standalone-1.0 (+respectful-public-check)","accept":"text/html,application/xhtml+xml,application/json"}});
    const reader = res.body?.getReader(); let total=0; const chunks=[];
    if (reader) {while (true) {const {value,done}=await reader.read();if (done) break;if (value) {total += value.byteLength;if (total > maxBytes) break;chunks.push(value);}}}
    const decoder = new TextDecoder();let body="";for (const c of chunks) body += decoder.decode(c,{stream:true});body += decoder.decode();
    return {ok:res.ok,status:res.status,url:res.url||url,body,bytes:total,blocked:BLOCK_RX.test(body)};
  } catch(e) {return {ok:false,status:0,url,body:"",bytes:0,blocked:false,error:String(e?.message||e)};} finally { clearTimeout(timer); }
}

export const DEAL_PAGE_RX = /(sale|outlet|clearance|deals?|offers?|promotion|promotions|last[\s_-]?chance|final[\s_-]?sale|end[\s_-]?of[\s_-]?season|hot[\s_-]?deals?|weekly[\s_-]?offers?|flash[\s_-]?sale|back[\s_-]?to[\s_-]?school|white[\s_-]?friday|national[\s_-]?day|saudi[\s_-]?national[\s_-]?day|snd96|عروض|تخفيضات|خصومات|أوتلت|اوتلت|تصفية|آخر\s*فرصة|اليوم\s*الوطني)/i;
export const NATIONAL_DAY_RX = /(saudi\s*national\s*day|ksa\s*national\s*day|national[\s_-]?day|snd96|اليوم\s*الوطني(?:\s*السعودي)?)/i;

export function discoverDealPageLinks(html, pageUrl, max=12) {
  const links=[]; const seen=new Set();
  for (const m of html.matchAll(/<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)) {
    const url=normalizeUrl(m[1],pageUrl);if (!url || !sameHostOrChild(url,pageUrl) || seen.has(url)) continue;
    const label=cleanText(m[2]), hay=`${label} ${url}`;if (!DEAL_PAGE_RX.test(hay)) continue;
    seen.add(url); links.push({url,label:label||url});if (links.length>=max) break;
  }
  return links;
}

export function classifyProductCategory(p={}) {
  const text=`${p.title||""} ${p.category||""} ${p.brand||""}`.toLowerCase();
  const rules=[["عطور", /(perfume|parfum|eau de|fragrance|عطر|عطور|عود|مسك)/i],["مكياج وجمال", /(makeup|lipstick|mascara|foundation|concealer|blush|beauty|cosmetic|مكياج|روج|ماسكارا|تجميل)/i],["عناية", /(skincare|skin care|hair care|conditioner|shampoo|serum|cream|lotion|razor|grooming|عناية|شامبو|بلسم|سيروم|كريم|حلاقة)/i],["أحذية", /(shoe|shoes|sneaker|sneakers|trainer|sandals?|boots?|slippers?|حذاء|أحذية|جزمة|صندل|شبشب)/i],["شنط وإكسسوارات", /(bag|bags|backpack|handbag|wallet|luggage|suitcase|belt|sunglass|شنطة|شنط|حقيبة|محفظة|نظارة|حزام)/i],["ملابس", /(shirt|t-?shirt|jersey|dress|hoodie|jacket|pants|trousers|jeans|abaya|thobe|clothing|apparel|قميص|تيشيرت|فستان|جاكيت|بنطال|جينز|عباية|ثوب|ملابس)/i],["جوالات وإلكترونيات", /(iphone|galaxy|smartphone|mobile|phone|tablet|ipad|laptop|monitor|television|\btv\b|headphone|earbuds|charger|ssd|gpu|console|playstation|xbox|جوال|هاتف|لاب ?توب|كمبيوتر|شاشة|تلفزيون|سماعة|شاحن|إلكترونيات)/i],["ساعات ومجوهرات", /(watch|watches|jewel|jewelry|jewellery|bracelet|necklace|ring|ساعة|ساعات|مجوهرات|خاتم|سوار|قلادة)/i],["أطفال", /(baby|babies|kids?|children|toy|toys|stroller|diaper|أطفال|طفل|رضع|لعبة|ألعاب)/i],["منزل وأثاث", /(furniture|sofa|chair|table|mattress|home|kitchen|cookware|appliance|vacuum|أثاث|كنب|كرسي|طاولة|مرتبة|منزل|مطبخ|أجهزة منزلية)/i],["رياضة", /(sport|fitness|football|soccer|gym|running|كرة|رياضة|تمارين)/i],["سوبرماركت", /(grocery|food|beverage|coffee|snack|supermarket|بقالة|سوبرماركت|قهوة|طعام|مشروب)/i],["ألعاب رقمية", /(steam|game|gaming|digital code|software|subscription|اشتراك|برنامج|لعبة رقمية)/i]];
  for (const [cat,rx] of rules) if (rx.test(text)) return cat;
  return p.category || "منوع";
}

export function isSaudiNationalDayWindow(date=new Date()) {
  const y=date.getFullYear();const start=new Date(`${y}-07-25T00:00:00+03:00`);const end=new Date(`${y}-09-26T23:59:59+03:00`);return date>=start && date<=end;
}

export function seasonalInfo(...parts) {
  const text=parts.filter(Boolean).join(" ");if (NATIONAL_DAY_RX.test(text)) return {active:true,key:"saudi-national-day-96",label:"اليوم الوطني 96"};return {active:false,key:null,label:null};
}

export function marketChannelFor(source={}) {
  if (source.marketChannel === "global") return "global";if (source.marketChannel === "saudi") return "saudi";const f=String(source.saudiFulfillment||""),scope=String(source.countryScope||"");if (/international/i.test(f) && !/SA_storefront/i.test(scope)) return "global";if (/local|sa_storefront/i.test(f) || /SA/i.test(scope)) return "saudi";return "saudi";
}
