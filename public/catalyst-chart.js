"use strict";
/* Third-party-hosted TradingView chart. No scraping, read-back, market quote
 * publication, signal promotion or execution-grade data in GHAZI RADAR. */
(function(root){
  const WIDGET="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
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
      allow_symbol_change:true,calendar:false,hide_volume:false,
      support_host:"https://www.tradingview.com"};
  }
  if(typeof module==="object"&&module.exports)module.exports={safeSymbol,makeConfig,WIDGET};
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
    $("desk-chart-title").textContent=active+" · شارت TradingView · "+interval;
    $("desk-chart-notice").textContent=
      "الشارت مستضاف لدى TradingView مباشرة، والموقع لا ينسخ أسعاره أو يعيد نشرها ولا يستخدمها لتوليد تنبيه. يمكن أن يتطلب تحديد البورصة الصحيحة.";
    for(const b of document.querySelectorAll("[data-desk-tf]"))
      b.setAttribute("aria-pressed",String(b.dataset.deskTf===interval));
    return true;
  }
  function open(symbol){
    const valid=safeSymbol(symbol);
    if(!valid)return false;
    active=valid;interval="D";
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
  }
  root.GhaziCatalystChart={open,close};
  document.addEventListener("DOMContentLoaded",()=>{
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
