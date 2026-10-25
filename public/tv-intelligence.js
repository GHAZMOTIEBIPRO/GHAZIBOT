"use strict";
// TradingView embed widgets: the external chart and quote display that
// TradingView's free embeds allow (branding kept, data shown inside the widget
// only). Nothing is read back from the widgets: no data extraction, no input to
// the GHAZI engines, and TradingView's technical ratings stay TradingView's.
//
// Symbols were checked on a GitHub runner (tv-widget-probe.yml, runs
// 40233630558 and 40234894415, 2026-10-25): cash indices (SP:SPX, NASDAQ:NDX,
// DJ:DJI, TVC:RUT, CBOE:VIX) answer "only available on TradingView" in free
// embeds, so each index is shown through the ETF that tracks it, labelled as
// an ETF, with a link to the cash index on TradingView. CFDs are not used.
(function(root){
  const BASE="https://s3.tradingview.com/external-embedding/embed-widget-";
  const KINDS=new Set(["technical-analysis","symbol-info","symbol-profile","financials","timeline",
    "events","stock-heatmap","screener","advanced-chart"]);
  const SYMBOL_RE=/^[A-Z][A-Z0-9.-]{0,9}$/;
  // Listing exchange per TradingView (probe-verified); unknown tickers are
  // passed bare and TradingView picks the listing, which the caption says.
  const EXCHANGE={SPY:"AMEX",DIA:"AMEX",IWM:"AMEX",QQQ:"NASDAQ",
    AAPL:"NASDAQ",NVDA:"NASDAQ",MSFT:"NASDAQ",AMZN:"NASDAQ",META:"NASDAQ",GOOGL:"NASDAQ",TSLA:"NASDAQ",
    AVGO:"NASDAQ",AMD:"NASDAQ",MU:"NASDAQ",GILD:"NASDAQ",AMGN:"NASDAQ",ORCL:"NYSE",BAC:"NYSE",OXY:"NYSE",
    CVX:"NYSE",GSK:"NYSE",MRK:"NYSE",ABBV:"NYSE",NVS:"NYSE",TAK:"NYSE",LLY:"NYSE",
    RGC:"NASDAQ",BNAI:"NASDAQ",RGTI:"NASDAQ",SOUN:"NASDAQ",IONQ:"NYSE",RKLB:"NASDAQ",ASTS:"NASDAQ",
    PLTR:"NASDAQ",SOFI:"NASDAQ"};
  // US cash indices: not renderable in free embeds; shown through their ETF.
  const INDEX_VIEWS={
    SPX:{name:"S&P 500",etf:"SPY",cash:"SP-SPX"},NDX:{name:"Nasdaq 100",etf:"QQQ",cash:"NASDAQ-NDX"},
    DJI:{name:"Dow Jones",etf:"DIA",cash:"DJ-DJI"},RUT:{name:"Russell 2000",etf:"IWM",cash:"TVC-RUT"},
    VIX:{name:"VIX",etf:null,cash:"CBOE-VIX"}};
  const INDICES=Object.keys(INDEX_VIEWS);
  const INTERVALS=[["5","5 دقائق"],["15","15 دقيقة"],["60","ساعة"],["240","4 ساعات"],["D","يومي"],["W","أسبوعي"]];
  const COMMON={colorTheme:"dark",isTransparent:true,locale:"ar_AE",width:"100%"};

  // What the widget will actually show for a ticker, and how to label it.
  function resolve(symbol){
    const value=String(symbol||"").trim().toUpperCase();
    if(!SYMBOL_RE.test(value))return null;
    const index=INDEX_VIEWS[value];
    const cashUrl=index?"https://www.tradingview.com/symbols/"+index.cash+"/":null;
    if(index&&!index.etf)return {input:value,tv:null,kind:"UNAVAILABLE",cash_url:cashUrl,
      note_ar:index.name+" النقدي غير متاح في أدوات TradingView المجانية، ولا نعرض بديلًا مختلفًا عنه."};
    if(index)return {input:value,tv:EXCHANGE[index.etf]+":"+index.etf,kind:"ETF_PROXY",cash_url:cashUrl,
      note_ar:"يُعرض صندوق "+index.etf+" الذي يتتبع "+index.name+"؛ ليس المؤشر النقدي "+value+
        " (غير متاح في الأدوات المجانية). السعر والنسب تختلف عن المؤشر."};
    const exchange=EXCHANGE[value];
    return {input:value,tv:exchange?exchange+":"+value:value,kind:"LISTED",cash_url:null,
      note_ar:exchange?"السهم "+value+" المدرج في "+exchange+".":"البورصة لم تُحدد لدينا؛ TradingView يختار إدراج "+value+"."};
  }

  function tvSymbol(symbol){return resolve(symbol)?.tv||null;}

  function config(kind,symbol,interval){
    if(!KINDS.has(kind))return null;
    const needsSymbol=!["events","stock-heatmap","screener"].includes(kind);
    const sym=needsSymbol?tvSymbol(symbol):null;
    if(needsSymbol&&!sym)return null;
    switch(kind){
      case "advanced-chart":{
        const iv=INTERVALS.some(([v])=>v===interval)?interval:"D";
        return {autosize:true,symbol:sym,interval:iv,timezone:"America/New_York",theme:"dark",style:"1",
          locale:"ar_AE",allow_symbol_change:false,hide_side_toolbar:true,withdateranges:true,
          support_host:"https://www.tradingview.com"};
      }
      case "technical-analysis":
        return {...COMMON,symbol:sym,interval:"1D",height:450,showIntervalTabs:true,displayMode:"single"};
      case "symbol-info": return {...COMMON,symbol:sym};
      case "symbol-profile": return {...COMMON,symbol:sym,height:420};
      case "financials": return {...COMMON,symbol:sym,height:520,displayMode:"regular"};
      case "timeline": return {...COMMON,symbol:sym,feedMode:"symbol",height:520,displayMode:"regular"};
      case "events": return {...COMMON,height:520,importanceFilter:"0,1",countryFilter:"us"};
      case "stock-heatmap":
        return {...COMMON,dataSource:"SPX500",grouping:"sector",blockSize:"market_cap_basic",blockColor:"change",
          hasTopBar:false,isDataSetEnabled:false,isZoomEnabled:true,hasSymbolTooltip:true,isMonoSize:false,
          symbolUrl:"",exchanges:[],height:520};
      case "screener":
        return {...COMMON,height:560,defaultColumn:"overview",defaultScreen:"most_capitalized",market:"america",
          showToolbar:true};
      default: return null;
    }
  }

  function widgetSrc(kind){return KINDS.has(kind)?BASE+kind+".js":null;}

  function mount(slot,kind,cfg){
    if(!slot||!cfg||typeof document==="undefined")return false;
    slot.replaceChildren();
    const holder=document.createElement("div");
    holder.className="tradingview-widget-container";
    if(kind==="advanced-chart")holder.style.height="100%";
    const inner=document.createElement("div");
    inner.className="tradingview-widget-container__widget";
    if(kind==="advanced-chart")inner.style.height="100%";
    const script=document.createElement("script");
    script.type="text/javascript";script.async=true;
    script.src=widgetSrc(kind);
    script.textContent=JSON.stringify(cfg);
    holder.append(inner,script);slot.append(holder);
    slot.dataset.mounted=kind+":"+(cfg.symbol||"")+":"+(cfg.interval||"");
    return true;
  }

  function unavailable(slot,info){
    if(!slot||typeof document==="undefined")return;
    slot.replaceChildren();
    const p=document.createElement("p");p.className="terminal-empty";p.textContent=info.note_ar;
    slot.append(p);
    if(info.cash_url){
      const a=document.createElement("a");a.href=info.cash_url;a.target="_blank";a.rel="noopener";
      a.textContent="افتح "+info.input+" على TradingView ↗";slot.append(a);
    }
    slot.dataset.mounted="unavailable:"+info.input;
  }

  // Load a widget only when its slot becomes visible (hidden tabs never load).
  function whenVisible(el,fn){
    if(!el)return;
    if(typeof IntersectionObserver==="undefined"){fn();return;}
    const io=new IntersectionObserver(entries=>{
      if(entries.some(e=>e.isIntersecting)){io.disconnect();fn();}
    },{rootMargin:"200px"});
    io.observe(el);
  }

  const $=id=>typeof document!=="undefined"?document.getElementById(id):null;

  function caption(info,interval){
    const frame=(INTERVALS.find(([v])=>v===interval)||INTERVALS[4])[1];
    return "الشارت الخارجي — TradingView · "+(info.tv||info.input)+" · الفريم: "+frame+" · "+info.note_ar+
      " الأسعار والتوقيت من TradingView داخل الأداة؛ لا تُستخرج ولا تغذي تحليل غازي رادار.";
  }

  // A chart view: symbol buttons + interval buttons + one advanced chart.
  // Container data-attributes: data-tv-chart-view, data-symbols="A,B,C".
  function chartView(box){
    if(!box||box.dataset.ready)return;
    box.dataset.ready="1";
    const symbols=String(box.dataset.symbols||"").split(",").map(s=>s.trim().toUpperCase()).filter(s=>resolve(s));
    if(!symbols.length)return;
    const symbolBar=document.createElement("div");symbolBar.className="ghazi-tv-buttons";
    symbolBar.setAttribute("role","group");symbolBar.setAttribute("aria-label","اختيار الرمز للشارت الخارجي");
    const frameBar=document.createElement("div");frameBar.className="ghazi-tv-buttons";
    frameBar.setAttribute("role","group");frameBar.setAttribute("aria-label","فريم الشارت الخارجي");
    const note=document.createElement("p");note.className="terminal-footnote";
    const slot=document.createElement("div");slot.className="ghazi-tv-slot ghazi-tv-slot--chart";
    const link=document.createElement("p");link.className="terminal-footnote";
    box.append(symbolBar,frameBar,slot,note,link);
    let current={symbol:symbols[0],interval:"D"};
    const press=()=>{
      for(const b of symbolBar.children)b.setAttribute("aria-pressed",String(b.dataset.symbol===current.symbol));
      for(const b of frameBar.children)b.setAttribute("aria-pressed",String(b.dataset.interval===current.interval));
    };
    const draw=()=>{
      const info=resolve(current.symbol);
      press();
      note.textContent=caption(info,current.interval);
      link.replaceChildren();
      if(info.cash_url){
        const a=document.createElement("a");a.href=info.cash_url;a.target="_blank";a.rel="noopener";
        a.textContent="المؤشر النقدي "+info.input+" على TradingView ↗";link.append(a);
      }
      if(info.kind==="UNAVAILABLE"){unavailable(slot,info);return;}
      mount(slot,"advanced-chart",config("advanced-chart",current.symbol,current.interval));
    };
    for(const sym of symbols){
      const b=document.createElement("button");b.type="button";b.className="secondary-button";
      b.dataset.symbol=sym;b.textContent=INDEX_VIEWS[sym]?INDEX_VIEWS[sym].name:sym;
      b.addEventListener("click",()=>{current={...current,symbol:sym};draw();});
      symbolBar.append(b);
    }
    for(const [value,label] of INTERVALS){
      const b=document.createElement("button");b.type="button";b.className="secondary-button";
      b.dataset.interval=value;b.textContent=label;
      b.addEventListener("click",()=>{current={...current,interval:value};draw();});
      frameBar.append(b);
    }
    box.ghaziShow=symbol=>{const s=String(symbol||"").toUpperCase();if(resolve(s)){current={...current,symbol:s};draw();}};
    whenVisible(slot,draw);
  }

  let indexSymbol="SPX",stockSymbol=null;

  function renderIndex(symbol){
    indexSymbol=symbol;
    for(const b of document.querySelectorAll("[data-tv-index]"))
      b.setAttribute("aria-pressed",String(b.dataset.tvIndex===symbol));
    const info=resolve(symbol);
    if(info.kind==="UNAVAILABLE"){unavailable($("tv-index-ta"),info);unavailable($("tv-index-info"),info);return;}
    mount($("tv-index-ta"),"technical-analysis",config("technical-analysis",symbol));
    mount($("tv-index-info"),"symbol-info",config("symbol-info",symbol));
    const status=$("tv-index-status");if(status)status.textContent=info.note_ar;
  }

  function renderSymbol(symbol){
    const sym=String(symbol||"").trim().toUpperCase();
    const status=$("tv-stock-status");
    const info=resolve(sym);
    if(!info){if(status)status.textContent="رمز غير صالح.";return;}
    if(sym===stockSymbol)return;
    stockSymbol=sym;
    const input=$("tv-stock-input");if(input&&input.value.toUpperCase()!==sym)input.value=sym;
    if(status)status.textContent="عرض TradingView للرمز "+(info.tv||sym)+" — "+info.note_ar+
      " التحليل الفني آلي من TradingView وليس توصية من GHAZI.";
    const box=$("tv-stock-intel");
    if(info.kind==="UNAVAILABLE"){
      for(const id of ["tv-stock-ta","tv-stock-profile","tv-stock-financials","tv-stock-news"])unavailable($(id),info);
      return;
    }
    whenVisible(box,()=>{
      mount($("tv-stock-ta"),"technical-analysis",config("technical-analysis",sym));
      mount($("tv-stock-profile"),"symbol-profile",config("symbol-profile",sym));
      mount($("tv-stock-financials"),"financials",config("financials",sym));
      mount($("tv-stock-news"),"timeline",config("timeline",sym));
    });
  }

  function init(){
    if(typeof document==="undefined")return;
    const indices=$("tv-index-buttons");
    if(indices){
      for(const sym of INDICES){
        const b=document.createElement("button");
        b.type="button";b.className="secondary-button";b.dataset.tvIndex=sym;b.textContent=INDEX_VIEWS[sym].name;
        b.setAttribute("aria-pressed","false");
        b.addEventListener("click",()=>renderIndex(sym));
        indices.append(b);
      }
      whenVisible(indices,()=>renderIndex(indexSymbol));
    }
    for(const box of document.querySelectorAll("[data-tv-chart-view]"))chartView(box);
    for(const [id,kind] of [["tv-heatmap","stock-heatmap"],["tv-screener","screener"],["tv-calendar","events"]]){
      const slot=$(id);whenVisible(slot,()=>mount(slot,kind,config(kind)));
    }
    const form=$("tv-stock-form");
    form?.addEventListener("submit",event=>{
      event.preventDefault();renderSymbol($("tv-stock-input")?.value);
    });
    let initial=null;
    try{initial=new URLSearchParams(location.search).get("chart");}catch{initial=null;}
    renderSymbol(resolve(initial)?initial:"NVDA");
  }

  const api={config,tvSymbol,resolve,widgetSrc,renderSymbol,INDICES,INTERVALS,EXCHANGE};
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  if(root){
    root.GhaziTV=api;
    if(root.document){
      if(root.document.readyState==="loading")root.document.addEventListener("DOMContentLoaded",init);
      else init();
    }
  }
})(typeof window!=="undefined"?window:null);
