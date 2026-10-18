"use strict";
/* GHAZI RADAR responsive v2. Research OHLC only, no synthetic prices or live quote claims. */
(function () {
  const ROOT="https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/";
  const FEEDS={
    index:[ROOT+"bot-state/runtime/public/data/index_radar.json","./data/index_radar.json"],
    charts:[ROOT+"bot-state/runtime/public/data/index_charts.json","./data/index_charts.json"],
    brief:[ROOT+"bot-state/runtime/public/data/decision_brief.json","./data/decision_brief.json"],
    news:[ROOT+"bot-state/runtime/public/data/free_public_intelligence.json","./data/free_public_intelligence.json"],
    sec:[ROOT+"bot-state/runtime/public/data/sec_filing_pulse.json"],
    watch:[ROOT+"bot-state/runtime/public/data/stock_watch_charts.json"],
    gamma:[ROOT+"bot-state/runtime/public/data/free_gex_validation.json"],
  };
  const INDEX_ORDER=["SPX","NDX","DJI","RUT","VIX","SPY","QQQ","IWM","DIA"];
  const LARGE=["AAPL","NVDA","MSFT","AMZN","META","GOOGL","TSLA","AVGO","AMD","MU","ORCL","BAC","OXY","CVX","GILD"];
  const VOLATILE=["RGC","BNAI","RGTI","SOUN","IONQ","RKLB","ASTS","PLTR","SOFI"];
  const I_NAMES={SPX:"S&P 500",NDX:"Nasdaq 100",DJI:"Dow Jones",RUT:"Russell 2000",
    VIX:"Cboe VIX",SPY:"S&P 500 ETF",QQQ:"Nasdaq ETF",IWM:"Russell ETF",DIA:"Dow ETF"};
  const STATES={UP:"صاعد",DOWN:"هابط",MIXED:"محايد / مختلط",
    STALE:"قديم",INSUFFICIENT:"تاريخ غير كافٍ",UNAVAILABLE:"غير متاح"};
  const $=id=>document.getElementById(id);
  const txt=(tag,value,cls)=>{
    const item=document.createElement(tag);
    item.textContent=value;if(cls)item.className=cls;return item;
  };
  const put=(id,value)=>{const e=$(id);if(e)e.textContent=value;};
  const fmt=(value,places=2)=>typeof value==="number" && Number.isFinite(value)
    ?value.toLocaleString("en-US",{maximumFractionDigits:places}):"—";
  const validDate=value=>{
    const t=Date.parse(value||"");return Number.isFinite(t)?t:null;
  };
  const stamp=value=>{
    const t=validDate(value);
    return t===null?"غير محدد":new Intl.DateTimeFormat("en-GB",{
      dateStyle:"medium",timeStyle:"short",timeZone:"Asia/Riyadh"
    }).format(new Date(t));
  };
  const safeOfficial=url=>{
    try{const u=new URL(url);return u.protocol==="https:"&&!u.username&&!u.password &&
      (["www.sec.gov","sec.gov","www.fda.gov","fda.gov"].includes(u.hostname)
      ||u.hostname.endsWith(".fda.gov"))?u.href:null;}catch{return null;}
  };
  const safeResearch=url=>{
    try{const u=new URL(url);return u.protocol==="https:"&&!u.username&&!u.password &&
      (u.hostname==="news.google.com"||
       ["www.prnewswire.com","prnewswire.com",
        "www.globenewswire.com","globenewswire.com"].includes(u.hostname))
      ?u.href:null;}catch{return null;}
  };
  const state={panel:"indices",symbol:"SPX",tf:"1d",ema:true,quotes:null,
    charts:null,brief:null,news:null,sec:null,watchCharts:null,gamma:null,
    stockCharts:null,plot:null};
  const schemaOK={
    index:d=>d?.schema==="ghazi.index_research.v1" &&
      d.index_options_signal_authority===false,
    charts:d=>d?.schema==="ghazi.index_charts.v1" &&
      d.quote_execution_eligible===false &&
      d.data_role==="RESEARCH_ONLY_NOT_LICENSED_EXECUTION",
    brief:d=>d?.schema==="ghazi.public_decision.v1" &&
      d.live_trade_quotes_verified===false,
    news:d=>Array.isArray(d?.google_news_attention)&&d?.policy &&
      d.policy.google_news_rss_is_unofficial_search_not_official_confirmation===true,
    sec:d=>d?.schema==="ghazi.sec_issuer_pulse.v1" &&
      d.policy?.positive_news_inferred===false,
    watch:d=>d?.schema==="ghazi.stock_charts.v1" &&
      d.quote_execution_eligible===false &&
      d.data_role==="RESEARCH_ONLY_NOT_LICENSED_EXECUTION",
    gamma:d=>d?.policy==="shadow_validation_never_signal_authority" &&
      d.decision==="SHADOW_ONLY",
  };
  async function request(url,type){
    const response=await fetch(url+"?v="+Date.now(),{cache:"no-store"});
    if(!response.ok)throw Error("HTTP "+response.status);
    const data=await response.json();
    const t=validDate(data?.generated_at);
    if(t===null||t>Date.now()+5*60000||!schemaOK[type](data))
      throw Error("schema/timestamp invalid");
    return data;
  }
  async function loadFeed(type){
    const outcome=await Promise.allSettled(FEEDS[type].map(url=>request(url,type)));
    const ready=outcome.filter(x=>x.status==="fulfilled").map(x=>x.value);
    ready.sort((a,b)=>Date.parse(b.generated_at)-Date.parse(a.generated_at));
    return ready[0]||null;
  }
  const chip=(label,bias)=>{
    const c=bias==="UP"?"up":bias==="DOWN"?"down":
      bias==="STALE"||bias==="INSUFFICIENT"?"warn":"";
    return txt("span",label,"terminal-chip "+c);
  };
  const pair=(name,val)=>{
    const d=txt("div","","terminal-pair");d.append(txt("span",name),txt("span",val));return d;
  };
  const chartButton=(symbol,label="قراءة الشارت ↗")=>{
    const btn=txt("button",label,"terminal-card-action");
    btn.type="button";btn.dataset.chartSymbol=symbol;return btn;
  };
  function renderIndices(){
    const wrap=$("terminal-index-grid");if(!wrap)return;wrap.replaceChildren();
    const report=state.quotes;
    if(!report || !report.symbols){wrap.append(txt("p","تعذر تحميل تحليل المؤشرات. المصدر غير متاح حاليًا.","terminal-empty"));return;}
    let count=0;
    for(const symbol of INDEX_ORDER){
      const row=report.symbols[symbol];
      if(!row?.last_completed_session_date||!Number.isFinite(row.last_completed_close))continue;
      const card=txt("article","","terminal-card");
      const head=txt("div","","terminal-card-head");
      const name=txt("div","");
      name.append(txt("strong",symbol),txt("small"," · "+I_NAMES[symbol]));
      head.append(name,chip(STATES[row.daily?.bias]||"غير محدد",row.daily?.bias));
      card.append(head);
      card.append(txt("div",fmt(row.last_completed_close,2),"terminal-price"));
      card.append(pair("RSI14 يومي",fmt(row.daily?.rsi14,1)));
      card.append(pair("EMA20 / 50",fmt(row.daily?.ema_fast)+" / "+fmt(row.daily?.ema_slow)));
      const level=row.levels?.last_completed_session;
      card.append(pair("قمة / قاع الجلسة",fmt(level?.high)+" / "+fmt(level?.low)));
      card.append(txt("small","آخر جلسة مكتملة: "+row.last_completed_session_date));
      card.append(chartButton(symbol));
      wrap.append(card);count++;
    }
    if(!count)wrap.append(txt("p","لم تصل بيانات مؤشرات مكتملة موثوقة.","terminal-empty"));
    put("terminal-index-footnote","المصدر: "+String(report.method||"Yahoo / yfinance")+
      " · آخر إنشاء للتقرير: "+stamp(report.generated_at)+
      " · الشموع لا تعني سعر تداول لحظيًا.");
  }
  function stockCard(symbol,entry,newsCount,label){
    const card=txt("article","","terminal-stock-card");
    const title=txt("div","","terminal-stock-title");
    title.append(txt("strong",symbol),chip(entry?entry.rating||"رصد":"قائمة متابعة",
      entry?.direction_research==="CALL"?"UP":entry?.direction_research==="PUT"?"DOWN":null));
    card.append(title);
    card.append(txt("div",entry?fmt(entry.observed_price)+" $":"—","terminal-stock-price"));
    card.append(pair("اتجاه البحث",entry?.direction_research||"لا توجد قراءة"));
    card.append(pair("RVOL",fmt(entry?.rvol,2)));
    card.append(pair("درجة ترتيب بحثية",fmt(entry?.score,1)));
    card.append(pair("عناوين أخبار مطابقة",String(newsCount)));
    const stockSeries=state.watchCharts?.symbols?.[symbol]?.intervals;
    card.append(pair("شموع يومية / 15 دقيقة",
      (stockSeries?.["1d"]?.bars?.length||0)+" / "+(stockSeries?.["15m"]?.bars?.length||0)));
    card.append(txt("p",entry?"السعر عند التقرير: "+stamp(state.brief?.source_generated_at):
      "لم يظهر هذا السهم في تقرير الفرص الأخير. لا يوجد سعر مُثبت في هذا القسم."));
    const headline=Array.isArray(state.news?.google_news_attention)?
      state.news.google_news_attention.find(x=>x.symbol===symbol && safeResearch(x.url)):null;
    if(headline){
      const a=txt("a","آخر خبر بحثي: "+String(headline.headline||"").slice(0,90)+" ↗");
      a.href=safeResearch(headline.url);a.target="_blank";a.rel="noopener noreferrer";
      a.className="terminal-stock-news";card.append(a);
    }else{
      card.append(txt("small",state.news?.status==="DEGRADED"?
        "لا يوجد عنوان مطابق مثبت لهذا السهم؛ بعض مصادر الأخبار متعثرة حاليًا.":
        "لا يوجد عنوان خبر مطابق ومؤرخ في أحدث رصد؛ لا نفترض وجود محفز.","terminal-stock-news-missing"));
    }
    card.append(chartButton(symbol));return card;
  }
  function renderStocks(kind){
    const wrap=$(kind==="large"?"terminal-large-grid":"terminal-small-grid");
    if(!wrap)return;wrap.replaceChildren();
    const scan=Array.isArray(state.brief?.stocks)?state.brief.stocks:[];
    // Automatically surface newly scanned tickers, even before Yahoo returns
    // candles. They are unclassified watch stocks, NOT verified microcaps.
    const symbolOK=s=>typeof s==="string"&&
      /^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$/.test(s);
    const dynamic=[...scan.map(x=>x?.symbol),
      ...Object.keys(state.watchCharts?.symbols||{})].filter(s=>
      symbolOK(s)&&!LARGE.includes(s)&&!INDEX_ORDER.includes(s));
    const list=kind==="large"?LARGE:[...new Set([...VOLATILE,...dynamic])].slice(0,25);
    const lookup=new Map(scan.map(x=>[x.symbol,x]));
    const news=Array.isArray(state.news?.google_news_attention)?state.news.google_news_attention:[];
    const sorted=[...list].sort((a,b)=>(lookup.get(b)?.score||0)-(lookup.get(a)?.score||0));
    for(const symbol of sorted){
      const related=news.filter(x=>x.symbol===symbol);
      wrap.append(stockCard(symbol,lookup.get(symbol),related.length,kind));
    }
    if(kind==="small")put("terminal-stock-chart-health",
      state.watchCharts?"تغطية شارتات المراقبة: "+
        (state.watchCharts.coverage?.with_daily||0)+" من "+
        (state.watchCharts.coverage?.requested||0)+" سهمًا بشموع يومية · نشر "+
        stamp(state.watchCharts.generated_at):
        "لا يوجد تقرير شارتات الأسهم الخاصة بعد؛ سيُجلب آليًا بعد مهمة المؤشرات، ولا نخترع شموعًا.");
    put(kind==="large"?"terminal-large-note":"terminal-small-note",
      (kind==="large"?"قائمة الشركات الكبيرة والمعروفة":"قائمة الشركات المضاربية/مرتفعة الحركة؛ لا يُحسم حجم الرسملة دون مصدر مستقل")+
      " · وقت فحص الأسهم: "+stamp(state.brief?.source_generated_at)+
      " · أسعار الرصد ليست حية · لا تُفسَّر الدرجة كنسبة ربح.");
  }
  function newsCard(item,official){
    const card=txt("article","","terminal-news-item");
    const risky=item.event_type==="OFFERING_OR_DILUTION_REVIEW"||
      item.event_topic==="RISK_OR_ADVERSE_EVENT_MENTION";
    card.append(chip(risky?"تحذير / مراجعة":official?"إفصاح أصلي":"خبر تجميعي",risky?"DOWN":null));
    card.append(txt("h5",official?
      String(item.symbol||"—")+" · "+String(item.form||"إفصاح"):
      String(item.symbol||"—")+" · "+String(item.headline||"عنوان غير متاح")));
    card.append(txt("p",official?
      "التاريخ: "+String(item.filing_date||"—")+" · "+String(item.event_type||"مراجعة"):
      "نُشر: "+stamp(item.published_at)+" · اتجاه الخبر غير مؤكد"));
    const url=official?safeOfficial(item.source_url):safeResearch(item.url);
    if(url){
      const a=txt("a",official?"عرض الإفصاح الأصلي ↗":"فتح الخبر للمراجعة ↗");
      a.href=url;a.target="_blank";a.rel="noopener noreferrer";card.append(a);
    }
    return card;
  }
  function renderNews(){
    const sec=state.sec,feed=state.news,official=$("terminal-official-news");
    const publicBox=$("terminal-public-news");
    if(!official||!publicBox)return;
    official.replaceChildren();publicBox.replaceChildren();
    const officialReports=Array.isArray(sec?.filings)?
      sec.filings.filter(x=>x.original_filing_confirmed===true &&
        safeOfficial(x.source_url)).slice(0,12):[];
    for(const item of officialReports)official.append(newsCard(item,true));
    if(!officialReports.length)official.append(txt("p",
      "لا تتوفر إفصاحات SEC أصلية مؤكدة من آخر فحص؛ لا تُعامل أخبار التجميع بديلاً عنها.","terminal-empty"));
    const stories=Array.isArray(feed?.google_news_attention)?
      feed.google_news_attention.filter(x=>x.authority==="NEWS_SEARCH_ATTENTION_ONLY" &&
       x.positive_catalyst_verified===false &&
       x.issuer_release_authenticated===false &&
       x.market_direction==="UNKNOWN" &&
       safeResearch(x.url)&&validDate(x.published_at)!==null):[];
    for(const item of stories.slice(0,16))publicBox.append(newsCard(item,false));
    if(!stories.length)publicBox.append(txt("p",
      "لا تتوفر أخبار حديثة مؤهلة للعرض من المصدر البحثي.","terminal-empty"));
    const errors=[...(Object.entries(feed?.source_errors||{})).map(([k,v])=>k+": "+v),
      ...(Object.entries(sec?.coverage?.errors||{})).map(([k,v])=>"SEC "+k+": "+v)];
    put("terminal-news-status",
      "SEC: "+String(sec?.status||"غير متاح")+" · أخبار بحثية: "+stories.length+
      " · أحدث تقرير أخبار: "+stamp(feed?.generated_at)+
      (errors.length?" · أعطال موثقة: "+errors.slice(0,3).join("، "):"")+
      " · العنوان الإخباري لا يثبت قوة أثر الخبر.");
  }
  function uniqueValidBars(rows){
    const res=new Map();
    for(const c of Array.isArray(rows)?rows:[]){
      const validTime=typeof c.time==="string" ?
        /^\d{4}-\d{2}-\d{2}$/.test(c.time) && Number.isFinite(Date.parse(c.time)) :
        Number.isInteger(c.time)&&c.time>1000000000;
      if(!validTime)continue;
      if(["open","high","low","close"].some(k=>!Number.isFinite(c[k])||c[k]<=0))continue;
      if(c.low>Math.min(c.open,c.close)||c.high<Math.max(c.open,c.close))continue;
      res.set(c.time,{time:c.time,open:c.open,high:c.high,low:c.low,close:c.close});
    }
    return [...res.values()].sort((a,b)=>a.time<b.time?-1:a.time>b.time?1:0).slice(-160);
  }
  function ema(points,period){
    if(points.length<period)return [];
    let value=points[0].close,k=2/(period+1);
    return points.map((p,i)=>{
      value=p.close*k+value*(1-k);
      return {time:p.time,value:i>=period-1?Number(value.toFixed(5)):null};
    }).filter(x=>x.value!==null);
  }
  function rsi(points){
    if(points.length<16)return null;
    let gain=0,loss=0;
    for(let i=1;i<=14;i++){
      const d=points[i].close-points[i-1].close;
      gain+=Math.max(d,0);loss+=Math.max(-d,0);
    }
    gain/=14;loss/=14;
    for(let i=15;i<points.length;i++){
      const d=points[i].close-points[i-1].close;
      gain=(gain*13+Math.max(d,0))/14;
      loss=(loss*13+Math.max(-d,0))/14;
    }
    return loss===0?(gain>0?100:50):100-100/(1+gain/loss);
  }
  function atr(points){
    if(points.length<15)return null;
    let sum=0;
    const tr=i=>Math.max(points[i].high-points[i].low,
      Math.abs(points[i].high-points[i-1].close),
      Math.abs(points[i].low-points[i-1].close));
    for(let i=1;i<=14;i++)sum+=tr(i);
    let value=sum/14;
    for(let i=15;i<points.length;i++)value=(value*13+tr(i))/14;
    return value;
  }
  let activeChart=null;
  function clearPlot(){
    if(activeChart){try{activeChart.remove();}catch{}activeChart=null;}
    $("terminal-candle-chart")?.replaceChildren();
  }
  function createFallbackSVG(candles){
    const target=$("terminal-candle-chart");if(!target)return;
    const rows=candles.slice(-56);
    const lows=rows.map(x=>x.low),highs=rows.map(x=>x.high);
    let low=Math.min(...lows),high=Math.max(...highs);
    const padding=Math.max((high-low)*.05,.01);low-=padding;high+=padding;
    const ns="http://www.w3.org/2000/svg";
    const svg=document.createElementNS(ns,"svg");
    svg.setAttribute("viewBox","0 0 960 400");svg.setAttribute("width","100%");
    svg.setAttribute("height","100%");svg.setAttribute("aria-label","شموع OHLC مكتملة");
    const y=n=>365-(n-low)/(high-low)*320;
    for(let i=0;i<=4;i++){
      const line=document.createElementNS(ns,"line");line.setAttribute("x1","44");
      line.setAttribute("x2","930");line.setAttribute("y1",String(38+i*80));
      line.setAttribute("y2",String(38+i*80));line.setAttribute("stroke","#233449");svg.append(line);
    }
    rows.forEach((v,i)=>{
      const x=53+i*870/rows.length,c=v.close>=v.open?"#48d2ab":"#ef8591";
      const wick=document.createElementNS(ns,"line");
      wick.setAttribute("x1",String(x));wick.setAttribute("x2",String(x));
      wick.setAttribute("y1",String(y(v.high)));wick.setAttribute("y2",String(y(v.low)));
      wick.setAttribute("stroke",c);svg.append(wick);
      const bar=document.createElementNS(ns,"rect");
      bar.setAttribute("x",String(x-4));bar.setAttribute("y",String(Math.min(y(v.open),y(v.close))));
      bar.setAttribute("width","8");bar.setAttribute("height",String(Math.max(1,Math.abs(y(v.open)-y(v.close)))));
      bar.setAttribute("fill",c);svg.append(bar);
    });
    target.append(svg);
  }
  function plotCandles(bars,showEMA,levels){
    clearPlot();
    const target=$("terminal-candle-chart");if(!target)return;
    const lib=typeof LightweightCharts!=="undefined"?LightweightCharts:null;
    if(!lib?.createChart){createFallbackSVG(bars);return;}
    try{
      const chart=lib.createChart(target,{autoSize:true,
        layout:{background:{type:"solid",color:"#0a1422"},textColor:"#a9bbd0",attributionLogo:true},
        grid:{vertLines:{color:"#1a2a3d"},horzLines:{color:"#1a2a3d"}},
        timeScale:{timeVisible:typeof bars[0].time==="number",secondsVisible:false,
          borderColor:"#2a3f55"},
        rightPriceScale:{borderColor:"#2a3f55"},
        crosshair:{mode:1},
      });
      activeChart=chart;
      const candle=chart.addSeries?
        chart.addSeries(lib.CandlestickSeries,{upColor:"#3dc3a2",downColor:"#e67889",
          borderVisible:false,wickUpColor:"#3dc3a2",wickDownColor:"#e67889"}):
        chart.addCandlestickSeries({upColor:"#3dc3a2",downColor:"#e67889"});
      candle.setData(bars);
      if(showEMA){
        for(const [period,color] of [[20,"#e9ba65"],[50,"#6395f1"]]){
          const data=ema(bars,period);
          if(data.length){
            const line=chart.addSeries?
              chart.addSeries(lib.LineSeries,{color,lineWidth:2,priceLineVisible:false,
                lastValueVisible:false}):
              chart.addLineSeries({color,lineWidth:2});
            line.setData(data);
          }
        }
      }
      if(levels&&typeof candle.createPriceLine==="function"){
        for(const [k,label,color] of [["high","قمة الجلسة","#73bfdb"],
            ["low","قاع الجلسة","#e1ad77"]]){
          const price=levels[k];
          if(typeof price==="number"&&Number.isFinite(price))
            candle.createPriceLine({price,title:label,color,lineWidth:1,
              lineStyle:2,axisLabelVisible:true});
        }
      }
      chart.timeScale().fitContent();
    }catch(error){clearPlot();createFallbackSVG(bars);}
  }
  async function loadStockCharts(){
    if(state.stockCharts)return state.stockCharts;
    const urls=[ROOT+"bot-state/runtime/public/data/latest.json","./data/latest.json"];
    for(const url of urls){
      try{
        const res=await fetch(url+"?v="+Date.now(),{cache:"no-store"});
        if(!res.ok)continue;
        const d=await res.json();
        if(d&&Array.isArray(d.stocks)&&d.charts&&validDate(d.generated_at)!==null){
          state.stockCharts=d;return d;
        }
      }catch{}
    }
    return null;
  }
  function refreshSymbols(){
    const select=$("terminal-chart-symbol");if(!select)return;
    const current=state.symbol;
    const chartNames=Object.keys(state.charts?.symbols||{});
    const watched=Object.keys(state.watchCharts?.symbols||{});
    const fallback=Object.keys(state.stockCharts?.charts||{});
    const discoveries=(state.brief?.stocks||[]).map(x=>x?.symbol)
      .filter(s=>typeof s==="string"&&
        /^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$/.test(s)).slice(0,40);
    const known=[...new Set([...INDEX_ORDER,...LARGE,...VOLATILE,
      ...discoveries,...watched,...fallback])];
    select.replaceChildren();
    for(const symbol of known){
      const option=txt("option",symbol+" · "+(I_NAMES[symbol]||"سهم"));
      option.value=symbol;select.append(option);
    }
    state.symbol=known.includes(current)?current:"SPX";select.value=state.symbol;
  }
  const putMetric=(label,value)=>{
    const d=txt("div",""),p=txt("small",label),v=txt("strong",value);
    d.append(p,v);return d;
  };
  async function renderChart(){
    refreshSymbols();
    const symbol=state.symbol,tf=state.tf;
    const indexFrame=state.charts?.symbols?.[symbol]?.intervals?.[tf];
    const stockFrame=state.watchCharts?.symbols?.[symbol]?.intervals?.[tf];
    const frame=indexFrame||stockFrame;
    const stock=state.stockCharts?.charts?.[symbol];
    const usingStock=!frame&&!INDEX_ORDER.includes(symbol)&&tf==="1d"&&stock;
    const rows=uniqueValidBars(frame?.bars||(usingStock?stock.bars:[]));
    const levels=INDEX_ORDER.includes(symbol)?state.quotes?.symbols?.[symbol]?.levels?.last_completed_session:null;
    const select=$("terminal-chart-timeframe");
    if(select){
      for(const option of select.options){
        option.disabled=!INDEX_ORDER.includes(symbol) &&
          !state.watchCharts?.symbols?.[symbol]?.intervals?.[option.value] &&
          option.value!=="1d";
      }
    }
    const metric=$("terminal-chart-levels");if(metric)metric.replaceChildren();
    if(rows.length<2){
      clearPlot();
      put("terminal-chart-spot","—");put("terminal-chart-direction","لا توجد شموع OHLC منشورة");
      put("terminal-chart-date","—");
      put("terminal-chart-reading","لا توجد شموع مكتملة لهذا الرمز/الفريم في التقرير المتاح. لا نرسم شارتًا تقديريًا. "+
        (!INDEX_ORDER.includes(symbol)?"الأسهم تُعرض يوميًا فقط عندما تُنشر شموعها في تقرير الرادار.":"المؤشرات تحتاج نشر ملف شموع المؤشرات."));
      put("terminal-chart-scenario","لا تُعرض أهداف ATR دون شموع مكتملة كافية.");
      renderGamma(symbol);
      if(!INDEX_ORDER.includes(symbol)&&!state.stockCharts &&
         !state.watchCharts?.symbols?.[symbol]){
        await loadStockCharts();
        refreshSymbols();
        if(uniqueValidBars(state.stockCharts?.charts?.[symbol]?.bars).length>=2)return renderChart();
      }
      return;
    }
    const last=rows[rows.length-1],fast=ema(rows,20),slow=ema(rows,50);
    const emaFast=fast.at(-1)?.value,emaSlow=slow.at(-1)?.value;
    const strength=rsi(rows),range=atr(rows);
    const recent=rows.slice(-20);
    const high=Math.max(...recent.map(x=>x.high)),low=Math.min(...recent.map(x=>x.low));
    const bias=emaFast!==undefined&&emaSlow!==undefined?
      last.close>emaFast&&emaFast>emaSlow&&strength>=55?"UP":
      last.close<emaFast&&emaFast<emaSlow&&strength<=45?"DOWN":"MIXED":"INSUFFICIENT";
    put("terminal-chart-spot",fmt(last.close)+" "+(INDEX_ORDER.includes(symbol)?"":"$"));
    put("terminal-chart-direction",STATES[bias]||"قراءة بحثية");
    const isDaily=typeof last.time==="string";
    put("terminal-chart-date",(isDaily?"آخر جلسة: ":"آخر شمعة مكتملة بدأت: ")+
      (isDaily?last.time:stamp(new Date(last.time*1000).toISOString())));
    for(const [label,value] of [["RSI14",fmt(strength,1)],
      ["ATR14",fmt(range)],["EMA20",fmt(emaFast)],["EMA50",fmt(emaSlow)],
      ["قمة / قاع 20 شمعة",fmt(high)+" / "+fmt(low)]]){
      metric?.append(putMetric(label,value));
    }
    plotCandles(rows,state.ema,levels);
    const currentClose=last.close;
    put("terminal-chart-scenario",range!==null && Number.isFinite(range)?
      "سيناريو نطاق الحركة بـ ATR (ليس احتمالًا): إذا استمر الزخم، "+
      "±1 ATR: "+fmt(currentClose-range)+" إلى "+fmt(currentClose+range)+
      " · ±2 ATR: "+fmt(currentClose-2*range)+" إلى "+fmt(currentClose+2*range)+
      ". الاتجاه الفني "+(STATES[bias]||"غير كافٍ")+
      "؛ السيناريو لا يراعي الأخبار أو الفجوات المستقبلية، ولا يمثل توقع Gamma.":
      "لا يمكن حساب نطاق ATR موثوق لهذا الشارت؛ تحتاج 15 شمعة على الأقل.");
    renderGamma(symbol);
    const current=frame?.current_session_confirmed===true;
    const freshnessText=isDaily?"شارت جلسات يومية مكتملة":
      current?"شموع الجلسة الحالية مكتملة لكن المصدر غير مرخّص لحظيًا":
      "شموع مكتملة من جلسة قديمة/متأخرة، لا تستخدمها كسعر مباشر";
    const context=bias==="UP"?"السعر أعلى EMA20 وEMA50 مع RSI داعم للصعود":
      bias==="DOWN"?"السعر دون EMA20 وEMA50 مع RSI ضعيف":
      "اتجاه المتوسطات والـRSI غير متوافق أو لا توجد عينة كافية";
    put("terminal-chart-reading",symbol+" · "+(tf==="1d"?"يومي":tf)+
      " · "+context+" · نطاق آخر 20 شمعة "+fmt(low)+"–"+fmt(high)+
      " · "+freshnessText+". "+
      "التحليل وصفي ولا يتنبأ باحتمال الربح. مصدر الشموع: "+
      (stockFrame?"مراقبة الأسهم Yahoo — إنشاء التقرير: "+stamp(state.watchCharts?.generated_at):
       usingStock?"الرادار Yahoo — تاريخ التقرير: "+stamp(state.stockCharts?.generated_at):
       "Yahoo / yfinance — إنشاء التقرير: "+stamp(state.charts?.generated_at))+".");
  }
  function renderGamma(symbol){
    const grid=$("terminal-gamma-metrics");if(grid)grid.replaceChildren();
    if(symbol!=="SPX"&&symbol!=="SPY"&&symbol!=="NDX"&&symbol!=="QQQ"){
      put("terminal-gamma-status","غير متاح لهذا الرمز");
      put("terminal-gamma-note","لا توجد سلسلة عقود مرخصة أو مثبتة لهذا السهم؛ لا يمكن استنتاج Gamma من الشموع.");
      return;
    }
    // SPX research is NOT Nasdaq GEX and is not SPY option dealer inventory.
    if(symbol==="NDX"||symbol==="QQQ"){
      put("terminal-gamma-status","غير متاح للناسداك");
      put("terminal-gamma-note","ملف GEX المجاني يغطي سياق SPX فقط؛ لا يجوز نسخه على عقود NDX أو QQQ.");
      return;
    }
    const data=state.gamma;
    const published=validDate(data?.generated_at);
    const recent=published!==null && Date.now()-published<=4*86400000 &&
      published<Date.now()+300000;
    if(!recent){
      put("terminal-gamma-status","غير متاح / تقرير قديم");
      put("terminal-gamma-note","لا يوجد تقرير Gamma حديث صادق في المصدر. لا نستخدم الصفر أو تخمين Dealer GEX.");
      return;
    }
    const metrics=data.metrics||{};
    const val=(key)=>metrics[key]?.count>0 &&
      Number.isFinite(metrics[key]?.median)?metrics[key].median:null;
    const gex=val("gex"),flip=val("flip"),cw=val("call_wall"),pw=val("put_wall");
    put("terminal-gamma-status","SHADOW — سياق تجريبي");
    for(const [label,value,suffix] of [
      ["GEX بحثي (وحدة المصدر)",gex,""],
      ["Gamma Flip",flip,""],
      ["Call Wall",cw,""],
      ["Put Wall",pw,""]]){
      grid?.append(putMetric(label,value===null?"غير متاح":fmt(value,1)+suffix));
    }
    const actual=data.integrated_engines?.ghazi_gex_multi?.available===true;
    const families=metrics.gex?.count||0;
    const note="مصادر GEX رقمية: "+families+
      " · محرك السلسلة المتكاملة: "+(actual?"يملك مدخلاً بحثياً":"لا توجد سلسلة عقود صالحة")+
      " · "+(symbol==="SPY"?"هذه مستويات SPX وليست قيم خيارات SPY. ":"")+
      "الأرقام قد تأتي من مزود واحد ولا تثبت تمركز صانع السوق أو اتجاه الغد. "+
      "التقرير: "+stamp(data.generated_at)+".";
    put("terminal-gamma-note",note);
  }
  function choosePanel(panel){
    state.panel=panel;
    document.querySelectorAll(".terminal-tab").forEach(button=>{
      const active=button.dataset.terminalTab===panel;
      button.classList.toggle("active",active);
      button.setAttribute("aria-selected",String(active));
    });
    document.querySelectorAll(".terminal-panel").forEach(view=>{
      const on=view.id==="terminal-panel-"+panel;
      view.hidden=!on;view.classList.toggle("active",on);
    });
    if(panel==="chart")requestAnimationFrame(()=>renderChart());
    if(panel==="advanced")$("terminal-panel-advanced")?.scrollIntoView({block:"start",behavior:"smooth"});
  }
  function chooseChart(symbol){
    state.symbol=symbol;state.tf="1d";
    const tf=$("terminal-chart-timeframe");if(tf)tf.value="1d";
    choosePanel("chart");
    $("terminal-panel-chart")?.scrollIntoView({block:"start",behavior:"smooth"});
  }
  async function refresh(){
    const types=["index","charts","brief","news","sec","watch","gamma"];
    const read=await Promise.allSettled(types.map(loadFeed));
    [state.quotes,state.charts,state.brief,state.news,state.sec,
      state.watchCharts,state.gamma]=
      read.map(r=>r.status==="fulfilled"?r.value:null);
    put("terminal-data-state",state.quotes?"مؤشرات متاحة للبحث":"بيانات المؤشرات غير متاحة");
    put("terminal-data-time","آخر تحليل: "+stamp(state.quotes?.generated_at)+
      " · تقارير الأسهم: "+stamp(state.brief?.source_generated_at));
    renderIndices();renderStocks("large");renderStocks("small");renderNews();
    refreshSymbols();
    if(state.panel==="chart")renderChart();
  }
  if(typeof module!=="undefined"&&module.exports){
    module.exports={uniqueValidBars,ema,rsi,atr,safeOfficial,safeResearch};
  }
  if(typeof document==="undefined")return;
  document.querySelectorAll(".terminal-tab").forEach(button=>
    button.addEventListener("click",()=>choosePanel(button.dataset.terminalTab)));
  $("ghazi-terminal")?.addEventListener("click",event=>{
    const button=event.target.closest("[data-chart-symbol]");
    if(button)chooseChart(button.dataset.chartSymbol);
  });
  $("terminal-chart-symbol")?.addEventListener("change",event=>{
    state.symbol=event.target.value;state.tf="1d";
    $("terminal-chart-timeframe").value="1d";renderChart();
  });
  $("terminal-chart-timeframe")?.addEventListener("change",event=>{
    state.tf=event.target.value;renderChart();
  });
  $("terminal-show-ema")?.addEventListener("change",event=>{
    state.ema=event.target.checked;renderChart();
  });
  $("terminal-toggle-legacy")?.addEventListener("click",()=>{
    const old=$("legacy-dashboard");if(!old)return;
    old.hidden=!old.hidden;
    $("terminal-toggle-legacy").setAttribute("aria-expanded",String(!old.hidden));
    $("terminal-toggle-legacy").textContent=old.hidden?
      "عرض لوحة الأدوات التفصيلية ↓":"إخفاء لوحة الأدوات التفصيلية ↑";
    if(!old.hidden){old.scrollIntoView({block:"start",behavior:"smooth"});
      // The legacy chart may have initialized while hidden.
      if(typeof radarData!=="undefined"&&typeof renderMarketChart==="function"&&radarData)
        renderMarketChart(radarData);
    }
  });
  refresh();
  setInterval(refresh,5*60*1000);
})();
