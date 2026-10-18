"use strict";
/* Public index research: last completed sessions only, no options price authority. */
(() => {
  const ENDPOINTS = [
    "https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/index_radar.json",
    "./data/index_radar.json",
  ];
  const ORDER = ["SPX", "NDX", "DJI", "RUT", "VIX", "SPY", "QQQ", "IWM", "DIA"];
  const NAMES = {
    SPX: "ستاندرد آند بورز 500", NDX: "ناسداك 100",
    DJI: "داو جونز", RUT: "راسل 2000", VIX: "مؤشر الخوف VIX",
    SPY: "صندوق SPY", QQQ: "صندوق QQQ", IWM: "صندوق IWM", DIA: "صندوق DIA"
  };
  const BIAS = {
    UP:"صاعد بحثيًا", DOWN:"هابط بحثيًا", MIXED:"غير متوافق",
    INSUFFICIENT:"تاريخ غير كافٍ", STALE:"شموع قديمة", UNAVAILABLE:"غير متاح"
  };
  const $ = id => document.getElementById(id);
  const text = (tag, label, className) => {
    const element = document.createElement(tag);
    element.textContent = label;
    if (className) element.className = className;
    return element;
  };
  const set = (id, value) => {const el=$(id);if(el)el.textContent=value;};
  const fmt = (v, digits=2) => typeof v==="number" && Number.isFinite(v)
    ? v.toLocaleString("en-US",{maximumFractionDigits:digits}) : "—";
  const level = (part) => part && typeof part==="object"
    ? fmt(part.low) + " – " + fmt(part.high) : "—";
  const formatTime = (stamp) => {
    const date = new Date(stamp);
    return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat("en-GB",{
      timeZone:"Asia/Riyadh",dateStyle:"medium",timeStyle:"short"
    }).format(date) : "غير معروف";
  };
  const valid = data => data && data.schema==="ghazi.index_research.v1" &&
    data.data_role==="RESEARCH_ONLY_NOT_LICENSED_EXECUTION" &&
    data.index_options_signal_authority===false &&
    data.symbols && typeof data.symbols==="object" &&
    Number.isFinite(Date.parse(data.generated_at));
  async function download(path) {
    const response=await fetch(path+"?check="+Date.now(),{cache:"no-store"});
    if (!response.ok) throw Error("HTTP "+response.status);
    const data=await response.json();
    if (!valid(data)) throw Error("invalid schema/authority");
    const ms=Date.parse(data.generated_at);
    if (ms > Date.now()+5*60000) throw Error("future timestamp");
    return data;
  }
  function addMetric(container,label,value) {
    const cell=text("div","", "ghazi-index-metric");
    cell.append(text("span",label),text("strong",value));
    container.append(cell);
  }
  function renderCard(row, symbol) {
    const card=text("article","", "ghazi-index-card");
    const header=text("header","", "ghazi-index-header");
    const heading=text("div","");
    heading.append(text("strong",symbol),text("small",NAMES[symbol]||symbol));
    header.append(heading);
    const day=row.daily||{};
    const dailyBias=String(day.bias||"UNAVAILABLE");
    const status=text("span",BIAS[dailyBias]||"غير متاح","ghazi-index-bias "+(dailyBias==="UP"?"rise":dailyBias==="DOWN"?"fall":"wait"));
    header.append(status);card.append(header);
    const body=text("div","","ghazi-index-values");
    addMetric(body,"آخر إغلاق مكتمل",fmt(row.last_completed_close));
    addMetric(body,"آخر جلسة مكتملة",row.last_completed_session_date||"—");
    if (["SPX","NDX","SPY","QQQ"].includes(symbol))
      addMetric(body,"5 دقائق",BIAS[row.m5?.bias]||"غير متاح");
    addMetric(body,"15 دقيقة",BIAS[row.m15?.bias]||"غير متاح");
    addMetric(body,"ساعة",BIAS[row.h1?.bias]||"غير متاح");
    addMetric(body,"RSI14 اليومي",fmt(day.rsi14,1));
    addMetric(body,"ATR14 اليومي",fmt(day.atr14));
    addMetric(body,"EMA"+(day.fast_period||20),fmt(day.ema_fast));
    addMetric(body,"EMA"+(day.slow_period||50),fmt(day.ema_slow));
    const levels=row.levels||{};
    addMetric(body,"قمة/قاع آخر جلسة",level(levels.last_completed_session));
    addMetric(body,"قمة/قاع الأسبوع السابق",level(levels.previous_week));
    addMetric(body,"قمة/قاع الشهر السابق",level(levels.previous_month));
    if(row.kind==="etf_proxy")addMetric(body,"VWAP جلسة اليوم",fmt(row.vwap_today));
    if(row.current_m5_confirmed===true && row.m5_source_bar_start)
      addMetric(body,"آخر شمعة 5m مكتملة",formatTime(row.m5_source_bar_start));
    if(row.current_intraday_bar_confirmed===true) {
      addMetric(body,"آخر إغلاق 15m مكتمل",fmt(row.last_finished_intraday_close));
      addMetric(body,"تغير الجلسة من الإغلاق السابق",row.change_from_last_completed_close_pct==null?"—":fmt(row.change_from_last_completed_close_pct)+"%");
    }
    card.append(body);
    const note=text("p","", "ghazi-index-note");
    const bar = row.current_intraday_bar_confirmed ? "آخر شمعة 15 دقيقة مكتملة بدأت "+formatTime(row.intraday_source_bar_start) :
      "لا تتوفر شموع 15 دقيقة حديثة ومؤكدة من هذه الجلسة";
    note.textContent=bar+" · "+(row.kind==="etf_proxy"?"صندوق متداول وليس مستوى المؤشر":"مؤشر بحثي غير تنفيذي");
    card.append(note);
    return card;
  }
  function consensus(rows) {
    const equity=["SPX","NDX","DJI","RUT"].map(symbol=>rows[symbol]?.daily?.bias||"UNAVAILABLE");
    const up=equity.filter(x=>x==="UP").length,down=equity.filter(x=>x==="DOWN").length;
    const valid=equity.filter(x=>["UP","DOWN","MIXED"].includes(x)).length;
    let label="غير مكتمل";
    if(valid===4 && up>=3)label="اتساع صعودي بحثي";
    else if(valid===4 && down>=3)label="اتساع هبوطي بحثي";
    else if(valid===4)label="اتجاهات متضاربة";
    const vix=rows.VIX?.daily?.bias||"UNAVAILABLE";
    return {label,detail:"من 4 مؤشرات: "+up+" صاعدة، "+down+" هابطة، "+(4-up-down)+" مختلطة/غير متاحة. VIX: "+
      (BIAS[vix]||"غير متاح")+". هذا مقياس وصفي للاتجاه وليس ضمانًا أو توصية CALL/PUT."};
  }
  function renderOverview(data) {
    const wrap=$("indices-overview-grid");
    if(!wrap)return;
    wrap.replaceChildren();
    const shown=["SPX","NDX","DJI","RUT","VIX"];
    const rows=data.symbols||{};
    let count=0;
    for(const symbol of shown) {
      const row=rows[symbol];
      if(!row || !row.last_completed_session_date || row.last_completed_close==null)continue;
      const card=text("article","","ghazi-market-pulse");
      card.append(text("strong",symbol+" · "+(NAMES[symbol]||symbol)));
      card.append(text("p",fmt(row.last_completed_close),"ghazi-market-figure"));
      const metrics=text("dl","");
      function item(label,value){
        const holder=text("div","");
        holder.append(text("dt",label),text("dd",value));
        metrics.append(holder);
      }
      item("اتجاه آخر يوم مكتمل",BIAS[row.daily?.bias]||"غير متاح");
      item("RSI يومي",fmt(row.daily?.rsi14,1));
      item("EMA "+(row.daily?.fast_period||20),fmt(row.daily?.ema_fast));
      item("قمة / قاع",level(row.levels?.last_completed_session));
      if(["SPX","NDX"].includes(symbol)){
        item("5 دقائق",BIAS[row.m5?.bias]||"غير متاح");
        item("15 دقيقة",BIAS[row.m15?.bias]||"غير متاح");
      }
      card.append(metrics);
      card.append(text("small","آخر جلسة مكتملة: "+row.last_completed_session_date+
        " · قراءة تاريخية قد تتأخر، ليست سعرًا حيًا"));
      wrap.append(card);
      count++;
    }
    set("indices-overview-status",
      "آخر تقرير: "+formatTime(data.generated_at)+" (الرياض) · "+
      count+" مؤشرات بتحليل تاريخي. "+
      (data.coverage?.intraday_current ?
        "تتوفر بعض شموع الجلسة الحالية المكتملة." :
        "السوق مغلق أو لا تتوفر شموع جلسة حالية مؤكدة؛ مستويات آخر جلسة ظاهرة."));
  }
  function render(data) {
    const age = Math.max(0,(Date.now()-Date.parse(data.generated_at))/60000);
    const coverage=data.coverage||{};
    set("index-radar-status","التقرير: "+formatTime(data.generated_at)+" بتوقيت الرياض · عمر الملف "+
      fmt(age/60,1)+" ساعة · يومي صالح: "+fmt(coverage.daily_validated,0)+"/"+fmt(coverage.symbols_requested,0));
    set("index-radar-source-note","المصدر: Yahoo/yfinance غير رسمي؛ أسعار وصناديق بحثية قد تتأخر. "+ 
      "الـ SPX ≠ SPY، والـ NDX ≠ QQQ. لا تستخدم هذه النتائج كإشارة عقود تنفيذية.");
    const summary=consensus(data.symbols);
    set("index-radar-consensus",summary.label);
    set("index-radar-consensus-description",summary.detail);
    renderOverview(data);
    const grid=$("index-radar-grid");
    if(!grid)return;
    grid.replaceChildren();
    for(const symbol of ORDER) {
      if(data.symbols[symbol])grid.append(renderCard(data.symbols[symbol],symbol));
    }
  }
  async function refresh() {
    const button=$("index-radar-refresh");
    if(button)button.disabled=true;
    set("index-radar-status","جارٍ جلب آخر تقرير مؤشرات منشور…");
    try {
      const responses=await Promise.allSettled(ENDPOINTS.map(download));
      const items=responses.filter(x=>x.status==="fulfilled").map(x=>x.value);
      if(!items.length)throw Error("no reports");
      items.sort((a,b)=>Date.parse(b.generated_at)-Date.parse(a.generated_at));
      const data=items[0];
      if(Date.now()-Date.parse(data.generated_at)>96*3600*1000)throw Error("old report");
      render(data);
    } catch(_) {
      set("index-radar-status","لا يوجد تقرير مؤشرات جديد صالح؛ لن نعرض اتجاهًا مستنتجًا من بيانات مجهولة أو قديمة.");
      set("indices-overview-status","تعذر تحميل تقرير المؤشرات من المصدر والنسخة الاحتياطية. لا تُختلق أسعار.");
      set("index-radar-consensus","WAIT — غير متاح");
      set("index-radar-consensus-description","فشل تحميل البيانات أو انتهت صلاحية التقرير.");
      set("index-radar-source-note","Yahoo مصدر بحثي لا يضمن الإتاحة أو السعر اللحظي.");
      $("index-radar-grid")?.replaceChildren();
    } finally {
      if(button)button.disabled=false;
    }
  }
  const button=$("index-radar-refresh");
  if(button)button.addEventListener("click",refresh);
  const overviewOpen=$("indices-overview-open");
  if(overviewOpen)overviewOpen.addEventListener("click",()=>{
    document.querySelector('.tab-button[data-tab="indices"]')?.click();
    $("tab-indices")?.scrollIntoView({behavior:"smooth",block:"start"});
  });
  refresh();
  // Only read published reports; refresh is not a licensed exchange data stream.
  setInterval(refresh, 10*60*1000);
})();
