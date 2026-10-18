"use strict";
/* GHAZI RADAR decision room. Never infer executable CALL/PUT from public research. */
(() => {
  const PATHS = {
    indices: ["https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/index_radar.json","./data/index_radar.json"],
    brief: ["https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/decision_brief.json","./data/decision_brief.json"],
    health: ["https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/data-status.json","./data/data-status.json"],
    outcomes: ["https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/stock_audit_public.json","./data/stock_audit_public.json"],
  };
  const el = id => document.getElementById(id);
  const set = (id,value) => {if(el(id))el(id).textContent=value;};
  const fmt = (n,digits=2) => typeof n==="number" && Number.isFinite(n)
    ? n.toLocaleString("en-US",{maximumFractionDigits:digits}) : "—";
  const fmtTime = t => {
    let d=new Date(t);return Number.isFinite(d.getTime())
      ? new Intl.DateTimeFormat("en-GB",{timeZone:"Asia/Riyadh",dateStyle:"medium",timeStyle:"short"}).format(d)
      : "غير متاح";
  };
  const minutesOld=(t,now=Date.now())=> {
    let n=Date.parse(t);return Number.isFinite(n)?(now-n)/60000:Infinity;
  };
  const isFresh=(t,maxM,now=Date.now()) => {
    let age=minutesOld(t,now);return age>=-5&&age<=maxM;
  };
  const valid=(type,d)=> {
    if(!d || typeof d!=="object"||!Number.isFinite(Date.parse(d.generated_at)))return false;
    if(type==="indices")return d.schema==="ghazi.index_research.v1"&&
      d.index_options_signal_authority===false&&d.data_role==="RESEARCH_ONLY_NOT_LICENSED_EXECUTION";
    if(type==="brief")return d.schema==="ghazi.public_decision.v1"&&
      d.authority==="RESEARCH_ONLY_NO_AUTOMATED_CALL_PUT"&&d.live_trade_quotes_verified===false;
    if(type==="outcomes")return d.schema==="ghazi.public_stock_outcomes.v1"&&
      d.decision_authority===false&&d.realized_portfolio_pnl===false;
    return !!d.option_provider_readiness;
  };
  async function one(url,type) {
    let res=await fetch(url+"?v="+Date.now(),{cache:"no-store"});
    if(!res.ok)throw Error("HTTP "+res.status);
    let d=await res.json();
    if(!valid(type,d)||minutesOld(d.generated_at)<-5)throw Error("bad report/provenance");
    return d;
  }
  async function read(type) {
    const done=await Promise.allSettled(PATHS[type].map(url=>one(url,type)));
    const found=done.filter(t=>t.status==="fulfilled").map(t=>t.value);
    if(!found.length)return null;
    found.sort((a,b)=>Date.parse(b.generated_at)-Date.parse(a.generated_at));
    return found[0];
  }
  function decision(indices,health,now=Date.now()) {
    const result={state:"WAIT",reason:"لا توجد بيانات مؤشرات موثوقة وحديثة",why:[],sample:false};
    if(!indices || !isFresh(indices.generated_at,120,now)){
      result.why.push("تقرير المؤشرات قديم أو غير متاح");return result;
    }
    const rows=indices.symbols||{},s=rows.SPX,n=rows.NDX,v=rows.VIX;
    if(!s||!n||!v){result.why.push("بيانات SPX أو NDX أو VIX ناقصة");return result;}
    const hours=[s.h1?.bias,n.h1?.bias],quarters=[s.m15?.bias,n.m15?.bias];
    if(!s.current_intraday_bar_confirmed||!n.current_intraday_bar_confirmed||
       !isFresh(s.intraday_source_bar_start,60,now)||
       !isFresh(n.intraday_source_bar_start,60,now)){
      result.why.push("لا توجد شموع 15 دقيقة مكتملة من الجلسة الحالية أو مصدرها متأخر");
      return result;
    }
    // Fresh index research isn't a licensed executable options feed.
    result.why.push("SPX وNDX: ساعة "+hours.join("/")+"، 15 دقيقة "+quarters.join("/"));
    if(!health || !isFresh(health.generated_at,180,now)) {
      result.why.push("تقرير جودة مصادر البوت غير متاح");return result;
    }
    const ready=health.option_provider_readiness||{};
    const up=hours.every(x=>x==="UP")&&quarters.every(x=>x==="UP");
    const down=hours.every(x=>x==="DOWN")&&quarters.every(x=>x==="DOWN");
    if(!up&&!down){
      result.reason="SPX وNDX غير متوافقين على الساعة و15 دقيقة؛ انتظار";
      return result;
    }
    if(v.daily?.bias==="UP"&&up){
      result.reason="المؤشرات صاعدة لكن VIX صاعد؛ تضارب مخاطرة يستلزم الانتظار";
      result.why.push("VIX في اتجاه صاعد بحثيًا");return result;
    }
    result.state=up?"UP_WATCH":"DOWN_WATCH";
    result.reason=up?"اتجاه SPX وNDX صعودي على فريمين — مراقبة بحثية فقط":
      "اتجاه SPX وNDX هبوطي على فريمين — مراقبة بحثية فقط";
    result.why.push(ready.production_quote_ready===true && ready.production_flow_ready===true ?
      "التقرير يدّعي بيانات أوبشن مؤهلة؛ يلزم التحقق من صلاحية كل عقد منفردًا":
      "أسعار وتدفقات الأوبشن غير مؤهلة للتنفيذ؛ لا توجد توصية عقد");
    return result;
  }
  function textNode(tag,value,cls){
    const x=document.createElement(tag);x.textContent=value;if(cls)x.className=cls;return x;
  }
  function renderStocks(brief){
    const wrap=el("decision-stock-list");if(!wrap)return;wrap.replaceChildren();
    const candidates=Array.isArray(brief?.stocks)?brief.stocks:[];
    if(!candidates.length){wrap.append(textNode("p","لا توجد فرص بحثية منشورة يمكن التحقق منها."));return;}
    candidates.slice(0,9).forEach(row=>{
      const card=textNode("article","","ghazi-decision-stock");
      const top=textNode("div","","ghazi-decision-card-top");
      top.append(textNode("strong",String(row.symbol||"—")),
        textNode("small","درجة "+fmt(row.score,1)+" · "+String(row.rating||"غير مصنفة")));
      card.append(top);
      const rowtext="الرصد: "+fmt(row.observed_price)+" · RVOL: "+fmt(row.rvol,1)+
        " · الاتجاه: "+String(row.direction_research||"UNKNOWN")+
        " · مستوى الإبطال: "+fmt(row.invalidation);
      card.append(textNode("p",rowtext));
      const catalyst=String(row.catalyst_source||"لا مصدر محفز مثبت");
      card.append(textNode("p","المحفز: "+catalyst+" — "+
        (row.is_verified_official_catalyst===true?"أكدته بيانات الرادار الرسمية":
          "لم يثبت تأكيد رسمي في هذا الملخص"),"ghazi-decision-note"));
      if(typeof row.catalyst_url==="string"&&row.catalyst_url.startsWith("https://")){
        const link=textNode("a","عرض مصدر المحفز ↗");link.href=row.catalyst_url;
        link.rel="noopener noreferrer";link.target="_blank";card.append(link);
      }
      wrap.append(card);
    });
  }
  function renderOutcomes(data,brief){
    const sample=data?.coverage||{};
    if(data && isFresh(data.generated_at,14*24*60)) {
      set("decision-outcome-status","تقرير تدقيق تاريخي موجود · "+fmtTime(data.generated_at));
      set("decision-outcome-sample",fmt(sample.eligible_records ?? sample.records,0));
      set("decision-outcome-covered",fmt(sample.covered_60m,0));
      set("decision-outcome-ambiguity",fmt(sample.ambiguous,0));
      set("decision-outcome-win-rate",data.proven_edge===true && typeof data.verified_win_rate_pct==="number"
        ? fmt(data.verified_win_rate_pct,1)+"%": "غير مثبت");
    }else{
      set("decision-outcome-status","تقرير تدقيق النتائج لم يصل أو ليس حديثًا بما يكفي");
      set("decision-outcome-sample","—");
      set("decision-outcome-covered","—");
      set("decision-outcome-ambiguity","—");
      set("decision-outcome-win-rate","غير مثبت");
    }
    set("decision-first-sightings",fmt(brief?.journal?.record_count_retained,0));
    set("decision-results-warning",
      "تواريخ الرصد الأولى لا تعني معاملات منفذة. الحالات الغامضة وغير المكتملة لا تُستبعد لإنتاج نسبة نجاح مرتفعة؛ ولا نعرض عائدًا صافيًا لصفقات لم ننفذها.");
  }
  function render(indices,brief,health,outcomes){
    const result=decision(indices,health);
    set("decision-main-state",result.state);
    set("decision-main-reason",result.reason);
    set("decision-data-basis",(result.why||[]).join(" · ")||"—");
    set("decision-room-update","رادار المؤشرات: "+(indices?fmtTime(indices.generated_at):"غير متاح")+
      " · مصادر الرادار: "+(health?fmtTime(health.generated_at):"غير متاح")+
      " · فرص الأسهم: "+(brief?fmtTime(brief.generated_at):"غير متاح"));
    const hasBrief=brief && isFresh(brief.source_generated_at,180);
    renderStocks(hasBrief?brief:null);
    renderOutcomes(outcomes,hasBrief?brief:null);
    const list=el("decision-catalysts");if(!list)return;list.replaceChildren();
    const items=hasBrief&&Array.isArray(brief.catalysts)?brief.catalysts.slice(0,8):[];
    if(!items.length){list.append(textNode("p","لا توجد أحداث موثقة وحديثة في التقرير المتاح."));return;}
    for (const c of items) {
      const item=textNode("div","","ghazi-decision-catalyst");
      item.append(textNode("strong",String(c.symbol||"—")+" · "+String(c.source||"مصدر غير محدد")));
      item.append(textNode("p",String(c.headline||"لا عنوان")+" · "+String(c.source_tier_reported||"تأكيد غير محدد")));
      if(c.source_url && String(c.source_url).startsWith("https://")){
        const link=textNode("a","فتح المصدر ↗");link.href=c.source_url;link.rel="noopener noreferrer";
        link.target="_blank";item.append(link);
      }
      list.append(item);
    }
  }
  async function refresh() {
    const btn=el("decision-room-refresh");if(btn)btn.disabled=true;
    set("decision-room-update","جارٍ التحقق من مصادر التقارير…");
    const result=await Promise.allSettled(["indices","brief","health","outcomes"].map(read));
    const data=result.map(x=>x.status==="fulfilled"?x.value:null);
    render(...data);
    if(btn)btn.disabled=false;
  }
  if(typeof module!=="undefined"&&module.exports)module.exports={decision};
  if(typeof document!=="undefined") {
    if(el("decision-room-refresh"))el("decision-room-refresh").addEventListener("click",refresh);
    refresh();
    setInterval(refresh,10*60*1000);
  }
})();
