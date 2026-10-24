"use strict";
/* Third-party-hosted TradingView chart. No scraping, read-back, market quote
 * publication, signal promotion or execution-grade data in GHAZI RADAR. */
(function(root){
  const WIDGET="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
  const ANALYSIS="https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js";
  const INTERVALS=new Set(["D","60","15","5"]);
  const SYMBOL=/^[A-Z][A-Z0-9.-]{0,7}$/;
  function safeSymbol(value){
    const symbol=String(value||"").trim().toUpperCase();
    return SYMBOL.test(symbol)?symbol:null;
  }
  function makeConfig(symbol,interval="D"){
    const resolved=safeSymbol(symbol);
    if(!resolved||!INTERVALS.has(interval))return null;
    return {autosize:true,symbol:resolved,interval,timezone:"America/New_York",
      theme:"dark",style:"1",locale:"ar_AE",backgroundColor:"#081522",
      allow_symbol_change:false,calendar:false,hide_volume:false,
      support_host:"https://www.tradingview.com"};
  }
  function analysisConfig(symbol,interval="D"){
    const cfg=makeConfig(symbol,interval);
    if(!cfg)return null;
    return {symbol:cfg.symbol,interval:({D:"1D","60":"1h","15":"15m","5":"5m"})[interval],
      width:"100%",height:450,colorTheme:"dark",isTransparent:true,
      locale:"ar_AE",showIntervalTabs:false,displayMode:"single"};
  }
  function selection(search){
    const params=new URLSearchParams(search);
    const symbol=safeSymbol(params.get("symbol"));
    const timeframe=params.get("tf")||"D";
    return symbol&&INTERVALS.has(timeframe)?{symbol,timeframe}:null;
  }
  if(typeof module==="object"&&module.exports)module.exports={safeSymbol,makeConfig,analysisConfig,selection,WIDGET,ANALYSIS};
  if(typeof document==="undefined"||!root)return;
  let active=null,interval="D";
  const $=id=>document.getElementById(id);
  function mount(){
    const cfg=makeConfig(active,interval),frame=$("desk-chart-widget");
    if(!cfg||!frame)return false;
    frame.replaceChildren();
    const wrapper=document.createElement("div");
    wrapper.className="tradingview-widget-container";
    wrapper.style.cssText="height:100%;width:100%";
    const content=document.createElement("div");
    content.className="tradingview-widget-container__widget";
    content.style.cssText="height:100%;width:100%";
    const script=document.createElement("script");
    script.type="text/javascript";script.async=true;script.src=WIDGET;
    script.textContent=JSON.stringify(cfg);
    wrapper.append(content,script);frame.append(wrapper);
    const technical=$("desk-analysis-widget");
    if(technical){
      technical.replaceChildren();
      const box=document.createElement("div");box.className="tradingview-widget-container";
      const body=document.createElement("div");body.className="tradingview-widget-container__widget";
      const loader=document.createElement("script");loader.type="text/javascript";
      loader.async=true;loader.src=ANALYSIS;loader.textContent=JSON.stringify(analysisConfig(active,interval));
      loader.onerror=()=>{technical.textContent="تعذر تحميل القراءة الفنية. استخدم رابط TradingView المباشر أدناه.";};
      box.append(body,loader);technical.append(box);
    }
    $("desk-analysis-title").textContent="قراءة فنية · "+active+" · "+interval;
    $("desk-analysis-link").href="https://www.tradingview.com/chart/?symbol="+encodeURIComponent(active);
    $("desk-chart-title").textContent=active+" · شارت TradingView · "+interval;
    $("desk-chart-notice").textContent=
      "الشارت مستضاف لدى TradingView مباشرة، والموقع لا ينسخ أسعاره أو يعيد نشرها ولا يستخدمها لتوليد تنبيه. يمكن أن يتطلب تحديد البورصة الصحيحة.";
    for(const b of document.querySelectorAll("[data-desk-tf]"))
      b.setAttribute("aria-pressed",String(b.dataset.deskTf===interval));
    return true;
  }
  function open(symbol,timeframe="D"){
    const valid=safeSymbol(symbol);
    if(!valid||!INTERVALS.has(timeframe))return false;
    active=valid;interval=timeframe;
    const panel=$("desk-chart-panel");
    if(!panel)return false;
    panel.hidden=false;
    mount();
    panel.scrollIntoView({behavior:"smooth",block:"start"});
    return true;
  }
  function close(){
    active=null;
    $("desk-chart-panel").hidden=true;
    $("desk-chart-widget").replaceChildren();
    $("desk-analysis-widget").replaceChildren();
  }
  root.GhaziCatalystChart={open,close};
  document.addEventListener("DOMContentLoaded",()=>{
    const form=$("desk-symbol-form");
    if(form)form.addEventListener("submit",event=>{
      event.preventDefault();
      const symbol=safeSymbol($("desk-symbol").value);
      $("desk-symbol-error").textContent=symbol?"":"أدخل رمز سهم أمريكي صحيحًا مثل NVDA.";
      if(symbol)open(symbol);
    });
    const requested=selection(root.location.search);
    if(requested)open(requested.symbol,requested.timeframe);
    const exit=$("desk-chart-close");
    if(exit)exit.addEventListener("click",close);
    for(const btn of document.querySelectorAll("[data-desk-tf]")){
      btn.addEventListener("click",()=>{
        if(!active)return;
        if(!INTERVALS.has(btn.dataset.deskTf))return;
        interval=btn.dataset.deskTf;
        mount();
      });
    }
  });
})(typeof window!=="undefined"?window:null);
