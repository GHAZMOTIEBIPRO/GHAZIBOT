"use strict";
// TradingView embed widgets: the public price/chart/news display route the
// rights matrix verifies (widget display with TradingView branding kept).
// Nothing is read back from the widgets: no data extraction, no input to the
// GHAZI engines, and TradingView's technical ratings stay TradingView's.
(function(root){
  const BASE="https://s3.tradingview.com/external-embedding/embed-widget-";
  const KINDS=new Set(["technical-analysis","symbol-info","symbol-profile","financials","timeline",
    "events","stock-heatmap","screener"]);
  const SYMBOL_RE=/^[A-Z][A-Z0-9.-]{0,9}$/;
  const INDICES=[
    ["SPX","SP:SPX","S&P 500"],["NDX","NASDAQ:NDX","Nasdaq 100"],["DJI","DJ:DJI","Dow Jones"],
    ["RUT","TVC:RUT","Russell 2000"],["VIX","TVC:VIX","VIX"],["SPY","AMEX:SPY","SPY"],
    ["QQQ","NASDAQ:QQQ","QQQ"],["IWM","AMEX:IWM","IWM"]];
  const MAPPED=Object.fromEntries(INDICES.map(([s,tv])=>[s,tv]));
  const COMMON={colorTheme:"dark",isTransparent:true,locale:"ar_AE",width:"100%"};

  function tvSymbol(symbol){
    const value=String(symbol||"").trim().toUpperCase();
    if(!SYMBOL_RE.test(value))return null;
    return MAPPED[value]||value;
  }

  function config(kind,symbol){
    if(!KINDS.has(kind))return null;
    const needsSymbol=!["events","stock-heatmap","screener"].includes(kind);
    const sym=needsSymbol?tvSymbol(symbol):null;
    if(needsSymbol&&!sym)return null;
    switch(kind){
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
    const inner=document.createElement("div");
    inner.className="tradingview-widget-container__widget";
    const script=document.createElement("script");
    script.type="text/javascript";script.async=true;
    script.src=widgetSrc(kind);
    script.textContent=JSON.stringify(cfg);
    holder.append(inner,script);slot.append(holder);
    slot.dataset.mounted=kind+":"+(cfg.symbol||"");
    return true;
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
  let indexSymbol="SPX",stockSymbol=null;

  function renderIndex(symbol){
    indexSymbol=symbol;
    for(const b of document.querySelectorAll("[data-tv-index]"))
      b.setAttribute("aria-pressed",String(b.dataset.tvIndex===symbol));
    mount($("tv-index-ta"),"technical-analysis",config("technical-analysis",symbol));
    mount($("tv-index-info"),"symbol-info",config("symbol-info",symbol));
  }

  function renderSymbol(symbol){
    const sym=String(symbol||"").trim().toUpperCase();
    const status=$("tv-stock-status");
    if(!tvSymbol(sym)){if(status)status.textContent="رمز غير صالح.";return;}
    if(sym===stockSymbol)return;
    stockSymbol=sym;
    const input=$("tv-stock-input");if(input&&input.value.toUpperCase()!==sym)input.value=sym;
    if(status)status.textContent="عرض TradingView للرمز "+sym+" — التحليل الفني آلي من TradingView وليس توصية من GHAZI.";
    const box=$("tv-stock-intel");
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
      for(const [sym,,name] of INDICES){
        const b=document.createElement("button");
        b.type="button";b.className="secondary-button";b.dataset.tvIndex=sym;b.textContent=name;
        b.setAttribute("aria-pressed","false");
        b.addEventListener("click",()=>renderIndex(sym));
        indices.append(b);
      }
      whenVisible(indices,()=>renderIndex(indexSymbol));
    }
    for(const [id,kind] of [["tv-heatmap","stock-heatmap"],["tv-screener","screener"],["tv-calendar","events"]]){
      const slot=$(id);whenVisible(slot,()=>mount(slot,kind,config(kind)));
    }
    const form=$("tv-stock-form");
    form?.addEventListener("submit",event=>{
      event.preventDefault();renderSymbol($("tv-stock-input")?.value);
    });
    let initial=null;
    try{initial=new URLSearchParams(location.search).get("chart");}catch{initial=null;}
    renderSymbol(tvSymbol(initial)?initial:"NVDA");
  }

  const api={config,tvSymbol,widgetSrc,renderSymbol,INDICES};
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  if(root){
    root.GhaziTV=api;
    if(root.document){
      if(root.document.readyState==="loading")root.document.addEventListener("DOMContentLoaded",init);
      else init();
    }
  }
})(typeof window!=="undefined"?window:null);
