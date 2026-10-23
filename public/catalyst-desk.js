"use strict";
/* Pure validator can be tested in Node without browser/network. */
(function(root){
  const REMOTE="https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/catalyst_watchlist.json";
  const ORDER={HIGH:3,MEDIUM:2,LOW:1};
  const TYPES={FDA_APPROVAL:"موافقة FDA",FDA_SUPPLEMENT:"تحديث FDA",FDA_RECALL:"سحب منتج",DILUTION_RISK:"خطر تخفيف",CHARTER_OR_REVERSE_SPLIT_REVIEW:"تعديل حقوق / تقسيم عكسي",LISTING_NOTICE:"إشعار إدراج",MATERIAL_AGREEMENT:"اتفاقية جوهرية",EARNINGS_RELEASE:"نتائج مالية",INSIDER_FILING:"إفصاح ملكية مطلعين",PERIODIC_REPORT:"تقرير دوري",TRIAL_RESULTS_POSTED:"نشر نتائج دراسة · الاتجاه غير مقيم",TRIAL_STATUS_REVIEW:"مراجعة حالة دراسة",TRIAL_REGISTRY_UPDATE:"تحديث سجل دراسة"};
  function official(url,source){
    try{
      const u=new URL(url);
      if(u.protocol!=="https:"||u.username||u.password)return null;
      if(source==="openFDA"&&(["www.accessdata.fda.gov","accessdata.fda.gov","www.fda.gov","fda.gov"].includes(u.hostname)))return u.href;
      if(source==="ClinicalTrials.gov"&&u.hostname==="clinicaltrials.gov"&&/^\/study\/NCT[0-9]{8}$/.test(u.pathname)&&!u.search&&!u.hash)return u.href;
      if(source==="SEC EDGAR"&&(u.hostname==="www.sec.gov"||u.hostname==="sec.gov"))return u.href;
    }catch{}
    return null;
  }
  function validate(report,now=Date.now()){
    if(!report||report.schema!=="ghazi.catalyst_watchlist.v1"||
       report.decision_authority!==false||report.execution_authority!==false||
       report.research_only!==true||!Array.isArray(report.watchlist)||report.watchlist.length>40)
      return {ok:false,reason:"REPORT_SCHEMA_INVALID",rows:[]};
    const timestamp=Date.parse(report.generated_at);
    if(!Number.isFinite(timestamp)||timestamp>now+300000||now-timestamp>72*3600000)
      return {ok:false,reason:"REPORT_STALE",rows:[]};
    const rows=[];
    for(const company of report.watchlist){
      if(!company||typeof company.symbol!=="string"||!/^[A-Z][A-Z0-9.-]{0,7}$/.test(company.symbol)||!Array.isArray(company.catalysts))
        continue;
      for(const event of company.catalysts.slice(0,6)){
        if(!event||event.symbol!==company.symbol||!Object.hasOwn(ORDER,event.importance)||!Object.hasOwn(TYPES,event.kind))
          continue;
        if(event.source==="openFDA"&&report.sources?.openfda!==true)continue;
        if(event.source==="SEC EDGAR"&&report.sources?.sec_edgar!==true)continue;
        if(event.source==="ClinicalTrials.gov"&&(report.sources?.clinicaltrials!==true||
           !["TRIAL_RESULTS_POSTED","TRIAL_STATUS_REVIEW","TRIAL_REGISTRY_UPDATE"].includes(event.kind)||
           event.official_registry_only!==true||event.outcome_direction!=="NOT_INFERRED"||
           !["exact_normalised_name","reviewed_sponsor_alias"].includes(event.match_method)||
           !official(event.source_url,event.source)))continue;
        if(!["openFDA","SEC EDGAR","ClinicalTrials.gov"].includes(event.source))continue;
        if(!/^\d{4}-\d{2}-\d{2}$/.test(event.date||"")||!Number.isFinite(Date.parse(event.date+"T00:00:00Z")))continue;
        const day=Date.parse(event.date+"T00:00:00Z");
        if(day>now||now-day>32*86400000||new Date(day).toISOString().slice(0,10)!==event.date)continue;
        rows.push({symbol:company.symbol,kind:event.kind,importance:event.importance,
          date:event.date,label:String(event.label||"").slice(0,160),
          reason:String(event.reason||"").slice(0,180),source:event.source,
          url:official(event.source_url,event.source),match:String(event.match_method||"").slice(0,45),
          dilution:company.dilution_risk===true,
          sub10:company.sub10_confirmed===true&&company.price_band==="UNDER_10"&&company.reason==="CURRENT_PERMITTED_QUOTE"});
      }
    }
    return {ok:true,generated_at:report.generated_at,rows,companyCount:new Set(rows.map(x=>x.symbol)).size,
      sources:report.sources||{},reportCount:report.watchlist.length};
  }
  function filter(rows,{q="",importance="all",kind="all",sort="importance"}={}){
    const query=String(q).trim().toUpperCase();
    const result=rows.filter(x=>(!query||[x.symbol,x.kind,x.label,x.reason].join(" ").toUpperCase().includes(query))&&
      (importance==="all"||importance===x.importance)&&
      (kind==="all"||kind===x.kind||(kind==="other"&&!x.kind.startsWith("FDA_")&&x.kind!=="DILUTION_RISK")));
    return result.sort((a,b)=>sort==="symbol"?a.symbol.localeCompare(b.symbol)||b.date.localeCompare(a.date):
      sort==="recent"?b.date.localeCompare(a.date)||ORDER[b.importance]-ORDER[a.importance]:
      ORDER[b.importance]-ORDER[a.importance]||b.date.localeCompare(a.date));
  }
  if(typeof module!=="undefined"&&module.exports)module.exports={validate,filter,official};
  if(typeof document==="undefined")return;
  const $=id=>document.getElementById(id);
  const state={rows:[]};
  const text=(node,value)=>{node.textContent=value;return node;};
  function el(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n;}
  function draw(){
    const rows=filter(state.rows,{q:$("desk-query").value,importance:$("desk-importance").value,
      kind:$("desk-kind").value,sort:$("desk-sort").value});
    const panel=$("desk-results");panel.replaceChildren();
    if(!rows.length){panel.append(el("p","empty","لا توجد أحداث مطابقة للشروط أو أن التقرير غير متاح."));return;}
    for(const row of rows){
      const card=el("article","event");
      const header=el("div","header");const head=el("div");
      head.append(el("h2","",row.symbol),el("span","line",row.date+" · "+row.source));
      header.append(head,el("span","pill"+(row.importance==="HIGH"?" warn":""),row.importance==="HIGH"?"أهمية مرتفعة":row.importance==="MEDIUM"?"متوسطة":"منخفضة"));
      card.append(header,el("p","name",TYPES[row.kind]||row.kind),el("p","line",row.label||"وصف الحدث غير متاح"));
      if(row.source==="ClinicalTrials.gov")card.append(el("p","line","سجل يقدمه الراعي؛ لا يثبت نجاح العلاج أو اتجاه السهم."));
      if(row.reason)card.append(el("p","line",row.reason));
      const facts=el("div","facts");
      facts.append(el("span","",row.match==="reviewed_sponsor_alias"?"اسم راعٍ مراجَع":"مطابقة ناشر/شركة"),
        el("span","",row.dilution?"يوجد خطر تخفيف يحتاج مراجعة":"ليس تأكيدًا للاتجاه"),
        el("span","",row.sub10?"أقل من 10$ بسعر مؤهل":"سعر السهم غير متحقق"));
      card.append(facts);
      const chartAction=el("button","chart-open","فتح شارت "+row.symbol+" · 1D / 1H / 15m / 5m");
      chartAction.type="button";
      chartAction.setAttribute("aria-label","عرض شارت TradingView للسهم "+row.symbol);
      chartAction.addEventListener("click",()=>{
        if(typeof window!=="undefined"&&window.GhaziCatalystChart)
          window.GhaziCatalystChart.open(row.symbol);
      });
      card.append(chartAction);
      if(row.url){const a=el("a","source","فتح المصدر الرسمي ↗");a.href=row.url;a.target="_blank";a.rel="noopener noreferrer";card.append(a);}
      else card.append(el("p","line","لم يُنشر رابط وثيقة صالح لهذه الواقعة."));
      panel.append(card);
    }
  }
  async function load(){
    $("desk-status").textContent="جاري فحص المصدر الرسمي…";
    try{
      const reply=await fetch(REMOTE+"?v="+Date.now(),{cache:"no-store"});
      if(!reply.ok)throw Error("HTTP "+reply.status);
      const view=validate(await reply.json());
      if(!view.ok)throw Error(view.reason);
      state.rows=view.rows;
      $("desk-status").textContent="بحث رسمي متاح · لا أسعار تنفيذية";
      $("desk-updated").textContent="وقت إعداد التقرير: "+new Date(view.generated_at).toLocaleString("ar-SA",{timeZone:"Asia/Riyadh"});
      $("desk-companies").textContent=String(view.companyCount);
      $("desk-events").textContent=String(view.rows.length);
      $("desk-dilution").textContent=String(new Set(view.rows.filter(r=>r.dilution).map(r=>r.symbol)).size);
      $("desk-sub10").textContent=String(new Set(view.rows.filter(r=>r.sub10).map(r=>r.symbol)).size);
      $("desk-rights").textContent="openFDA: "+(view.sources.openfda?"بيانات رسمية متاحة":"غير متاح")+
        " · SEC EDGAR: "+(view.sources.sec_edgar?"متاح":"غير متاح")+" · سجل الدراسات: "+(view.sources.clinicaltrials?(view.sources.clinicaltrials_status==="PARTIAL"?"متاح بتغطية جزئية":"متاح"):"غير متاح")+" · الفلاتر لا تحول المحفز إلى توصية.";
    }catch(e){
      state.rows=[];
      $("desk-status").textContent="البيانات غير متاحة";
      $("desk-updated").textContent="لم يتم استبدال التقرير ببيانات مصطنعة أو قديمة";
      $("desk-companies").textContent=$("desk-events").textContent=$("desk-dilution").textContent=$("desk-sub10").textContent="—";
      $("desk-rights").textContent="تعذر التحقق من التقرير: "+String(e.message).slice(0,90);
    }
    draw();
  }
  document.addEventListener("DOMContentLoaded",()=>{
    for(const id of ["desk-query","desk-importance","desk-kind","desk-sort"])
      $(id).addEventListener(id==="desk-query"?"input":"change",draw);
    $("desk-reload").addEventListener("click",load);
    load();
  });
})(typeof window!=="undefined"?window:undefined);