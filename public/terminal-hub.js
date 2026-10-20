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
    freeOptions:[ROOT+"bot-state/runtime/public/data/free_options_sources.json"],
    watch:[ROOT+"bot-state/runtime/public/data/stock_watch_charts.json"],
    structural:[ROOT+"bot-state/runtime/public/data/structural_watch.json"],
    sourceAgreement:[ROOT+"bot-state/runtime/public/data/source_agreement.json"],
    strength:[ROOT+"bot-state/runtime/public/data/site_strength.json"],
    gamma:[ROOT+"bot-state/runtime/public/data/free_gex_validation.json"],
    trust:[ROOT+"bot-state/runtime/public/data/free_data_health.json","./data/free_data_health.json"],
    runtime:[ROOT+"bot-state/runtime/public/data/data-status.json","./data/data-status.json"],
    audit:[ROOT+"bot-state/runtime/public/data/stock_audit_public.json"],
    oos:[ROOT+"bot-state/state/stocks/stock_walk_forward.json"],
    live:[ROOT+"bot-state/runtime/public/data/live_dashboard_status.json"],
    explosion:[ROOT+"bot-state/runtime/public/data/explosion_hunter.json"],
    classical:[ROOT+"bot-state/runtime/public/data/classical_direction.json"],
    liquidity:[ROOT+"bot-state/runtime/public/data/liquidity_map.json"],
    stageEval:[ROOT+"bot-state/runtime/public/data/explosion_stage_evaluation.json"],
    optionsAnalytics:[ROOT+"bot-state/runtime/public/data/options_analytics.json"],
    dataHub:[ROOT+"bot-state/runtime/public/data/data_hub.json"],
    modelLab:[ROOT+"bot-state/runtime/public/data/explosion_model_lab.json"],
    tracking:[ROOT+"bot-state/runtime/public/data/signal_tracking.json"],
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
  const state={panel:"overview",symbol:"SPX",tf:"1d",ema:true,quotes:null,
    charts:null,brief:null,news:null,sec:null,watchCharts:null,gamma:null,
    stockCharts:null,plot:null,trust:null,runtime:null,audit:null,structural:null,
    oos:null,sourceAgreement:null,freeOptions:null,strength:null,live:null,explosion:null,classical:null,liquidity:null,stageEval:null,optionsAnalytics:null,dataHub:null,modelLab:null,tracking:null,pendingSymbol:null};
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
    freeOptions:d=>d?.schema==="ghazi.free_options_source_pulse.v1" &&
      d.research_only===true && d.trading_authority===false &&
      d.option_execution_eligible===false &&
      d.policy?.third_party_filings_not_official_sec_confirmation===true &&
      d.policy?.no_automatic_options_orders===true &&
      Array.isArray(d.filingpulse?.events) &&
      d.filingpulse.events.length<=45 &&
      d.occ_open_interest?.not_live_quote===true &&
      d.tradier?.source_quotes_published===false,
    watch:d=>d?.schema==="ghazi.stock_charts.v1" &&
      d.quote_execution_eligible===false &&
      d.data_role==="RESEARCH_ONLY_NOT_LICENSED_EXECUTION",
    strength:d=>d?.schema==="ghazi.evidence_strength.v1" &&
      d.research_only===true && d.execution_authority===false &&
      d.score_basis==="RESEARCH_DATA_AND_VALIDATION_READINESS" &&
      d.score_is_prediction_win_rate===false &&
      d.score_is_realized_return===false &&
      d.score_includes_visual_ui_audit===false &&
      d.score_includes_unverified_live_quotes===false &&
      Number.isInteger(d.strength_score) &&
      d.strength_score>=0 && d.strength_score<=100 &&
      d.weights_sum===100 && Array.isArray(d.components) &&
      d.components.length===6 &&
      Math.abs(d.components.reduce((sum,c)=>
        sum+(Number.isFinite(c.earned)?c.earned:0),0)-
        d.strength_score)<=0.51 &&
      d.components.reduce((sum,c)=>
        sum+(Number.isFinite(c.maximum)?c.maximum:0),0)===100 &&
      d.components.every(c=>Number.isFinite(c.earned)&&
        Number.isFinite(c.maximum)&&c.earned>=0&&
        c.earned<=c.maximum && c.maximum>0),
    sourceAgreement:d=>d?.schema==="ghazi.source_consensus_status.v1" &&
      d.independent_price_comparison==="NOT_VERIFIED" &&
      d.independent_confirmations===0 && d.quote_execution_eligible===false &&
      d.research_only===true && d.price_data===null &&
      d.massive_market_data_published===false &&
      d.concordance_ratio===null,
    structural:d=>d?.schema==="ghazi.structural_watch.v1" &&
      d.research_only===true && d.option_execution_ready===false &&
      d.recommendation===false && Array.isArray(d.candidates) &&
      d.candidates.length<=60 &&
      ["RESEARCH_SNAPSHOT","STALE_OR_INVALID"].includes(d.status),
    gamma:d=>d?.policy==="shadow_validation_never_signal_authority" &&
      d.decision==="SHADOW_ONLY",
    trust:d=>d?.version==="FREE_DATA_FABRIC_V2" &&
      d?.policy?.semantic_validation_required===true &&
      d?.policy?.http_success_is_not_data_success===true &&
      Array.isArray(d.sources) && d.sources.length<=25,
    runtime:d=>["healthy","degraded","critical","unavailable"].includes(
      String(d?.status||"").toLowerCase()) &&
      d?.option_provider_readiness?.production_quote_ready!==undefined &&
      d?.row_counts && d?.quality_counts,
    classical:d=>d?.schema==="ghazi.classical_direction_public.v1"&&d.research_only===true&&
      d.execution_authority===false&&d.probability===null&&d.option_data_used_for_direction===false&&
      Array.isArray(d.companies),
    explosion:d=>d?.schema==="ghazi.explosion_hunter_public.v1"&&d.research_only===true&&
      d.score_is_probability===false&&d.execution_authority===false&&Array.isArray(d.candidates),
    tracking:d=>d?.schema==="ghazi.signal_tracking.v1"&&d.decision_authority===false&&
      d.is_win_probability===false&&d.symbols&&typeof d.symbols==="object",
    modelLab:d=>d?.schema==="ghazi.explosion_model_lab.v1"&&d.research_only===true&&
      d.live_rules_changed===false&&d.models&&typeof d.models==="object",
    dataHub:d=>d?.schema==="ghazi.data_hub.v1"&&d.decision_authority===false&&Array.isArray(d.datasets),
    optionsAnalytics:d=>d?.schema==="ghazi.options_analytics.v1"&&d.research_only===true&&
      d.execution_grade===false&&d.raw_quotes_published===false&&d.symbols&&typeof d.symbols==="object",
    stageEval:d=>d?.schema==="ghazi.explosion_stage_evaluation.v1"&&d.research_only===true&&
      d.decision_authority===false&&d.score_is_probability===false&&d.stages&&typeof d.stages==="object",
    liquidity:d=>d?.schema==="ghazi.liquidity_map.v1"&&d.order_book_available===false&&
      d.symbols&&typeof d.symbols==="object",
    live:d=>d?.decision_authority===false&&d?.contains_secrets===false&&
      d?.paths&&typeof d.paths==="object",
    oos:d=>d?.mode==="EXPANDING_SESSION_WALK_FORWARD" &&
      d.decision_authority===false &&
      d.live_promotion_allowed===false &&
      d.data_policy?.random_split_allowed===false &&
      d.data_policy?.future_session_training_allowed===false,
    audit:d=>d?.schema==="ghazi.public_stock_outcomes.v1" &&
      d?.mode==="HISTORICAL_5M_OUTCOME_AUDIT" &&
      d?.decision_authority===false &&
      d?.promotion_gate?.live_promotion_allowed===false &&
      d?.verified_win_rate_pct===null &&
      Number.isInteger(d?.coverage?.records) &&
      Number.isInteger(d?.coverage?.covered_60m),
  };
  async function request(url,type){
    const response=await fetch(url+"?v="+Date.now(),{cache:"no-store"});
    if(!response.ok)throw Error("HTTP "+response.status);
    const data=await response.json();
    // The existing durable walk-forward report deliberately has no source
    // timestamp. Validate policy and numbers, but never imply data freshness.
    if(type==="oos"){
      if(!schemaOK.oos(data))throw Error("walk-forward policy invalid");
      return data;
    }
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
  const feedAgeHours=(stampValue)=>{
    const t=validDate(stampValue);
    return t!==null&&t<=Date.now()+300000?
      Math.max(0,(Date.now()-t)/3600000):null;
  };
  const pulse=(label,value,meta,kind="neutral")=>{
    const d=txt("article","","terminal-pulse "+kind);
    d.append(txt("small",label),txt("strong",value),txt("span",meta));
    return d;
  };
  function renderOverview(){
    const metrics=$("terminal-overview-pulse"),picks=$("terminal-overview-picks"),
      events=$("terminal-overview-events");
    if(!metrics||!picks||!events)return;
    metrics.replaceChildren();picks.replaceChildren();events.replaceChildren();
    const charts=state.watchCharts,scan=Array.isArray(state.brief?.stocks)?state.brief.stocks:[],
      news=Array.isArray(state.news?.google_news_attention)?state.news.google_news_attention:[],
      runtime=state.runtime,sec=state.sec;
    const indexCount=Number(state.charts?.coverage?.symbols||0);
    const watchCount=Number(charts?.coverage?.with_valid_charts||0);
    const watchRequested=Number(charts?.coverage?.requested||0);
    const quoteReady=runtime?.option_provider_readiness?.production_quote_ready===true;
    metrics.append(
      pulse("المؤشرات المشمولة",state.charts?String(indexCount):"—",
        "من تقرير البحث · "+stamp(state.charts?.generated_at)),
      pulse("شارتات الأسهم",charts?watchCount+" / "+watchRequested:"—",
        "مؤرخة · "+stamp(charts?.generated_at)),
      pulse("إفصاحات SEC المؤكدة",sec&&sec.status==="OK"?
        String(sec.coverage?.filings_verified??0):"غير متاح",
        "حالة المصدر: "+String(sec?.status||"غير متاح"),
        sec?.status==="OK"?"neutral":"caution"),
      pulse("الخيارات التنفيذية",quoteReady?"تحقق من العقد":"غير مؤهلة",
        "البوابة: "+String(runtime?.option_provider_readiness?.status||"غير متاح"),
        quoteReady?"neutral":"caution")
    );
    const age=feedAgeHours(state.brief?.source_generated_at);
    const stale=age===null||age>24;
    const ordered=scan.filter(q=>q&&/^[A-Z][A-Z0-9.-]{0,7}$/.test(q.symbol||"")&&
      Number.isFinite(q.score)).sort((a,b)=>b.score-a.score).slice(0,5);
    for(const item of ordered){
      const card=txt("article","","terminal-pick");
      const info=txt("div","","terminal-pick-main");
      const top=txt("div","","terminal-pick-title");
      top.append(txt("strong",item.symbol),
        chip(stale?"تاريخي":item.direction_research==="CALL"?
          "صعود بحثي":item.direction_research==="PUT"?"هبوط بحثي":"انتظار",
          stale?"STALE":item.direction_research==="CALL"?"UP":
          item.direction_research==="PUT"?"DOWN":null));
      info.append(top,txt("small","ترتيب بحثي "+fmt(item.score,1)+
        " · RVOL "+fmt(item.rvol,2)+" · "+String(item.stage||"مراقبة")));
      card.append(info,chartButton(item.symbol,"الشارت ↗"));
      picks.append(card);
    }
    if(!ordered.length)picks.append(txt("p","لا توجد فرص بحثية مؤهلة في آخر تقرير.","terminal-empty"));
    let shown=0;
    for(const story of news){
      if(shown>=4)break;
      if(story?.authority!=="NEWS_SEARCH_ATTENTION_ONLY"||
         story.issuer_release_authenticated!==false||
         story.positive_catalyst_verified!==false||
         !safeResearch(story.url)||validDate(story.published_at)===null)continue;
      const row=txt("article","","terminal-event");
      row.append(txt("span",String(story.symbol||"—"),"terminal-event-symbol"));
      const link=txt("a",String(story.headline||"خبر غير مسمى").slice(0,130));
      link.href=safeResearch(story.url);link.target="_blank";link.rel="noopener noreferrer";
      row.append(link,txt("small","خبر بحثي غير مؤكد · "+stamp(story.published_at)));
      events.append(row);shown++;
    }
    if(!shown)events.append(txt("p","لم تصل أخبار بحثية مؤهلة للعرض.","terminal-empty"));
    const agreement=typeof GhaziSourceAgreement!=="undefined"?
      GhaziSourceAgreement.evaluate(state.sourceAgreement):null;
    put("terminal-source-agreement-status",agreement?
      agreement.explanation+" · عدد مصادر الأسعار المرصودة: "+
      agreement.families+" · الشارتات البحثية: "+agreement.chartCount+
      " · الحالة: "+agreement.status:
      "لا يوجد تقرير حديث صالح عن اتفاق المصادر؛ لا نعتبر Yahoo ومكتباته مصدرين مستقلين.");
    const oos=typeof GhaziOOS!=="undefined"?
      GhaziOOS.evaluate(state.oos):null;
    const oosText=oos?oos.summary+" · تغطية 60 دقيقة: "+
      fmt(oos.coverage,2)+"% (شرط الاختبار: 90%) · جلسات مستقلة: "+
      oos.sessions+" · جلسات اختبار خارج العينة: "+oos.outSessions+
      " · حالات الاختبار: "+oos.outRecords+
      (oos.findings?(
        " · AUC ترتيب الدرجة: "+fmt(oos.findings.auc,2)+" (0.50 = عشوائي)"+
        " · نسبة الحالات الموجبة خارج العينة: "+fmt(100*oos.findings.basePositiveRate,1)+"%"+
        " مقابل الربع الأعلى: "+fmt(100*oos.findings.topQuartilePositiveRate,1)+"%"+
        (oos.findings.topQuartileMeanReturn===null?"":
          " · متوسط عائد 60 دقيقة للربع الأعلى: "+fmt(oos.findings.topQuartileMeanReturn,2)+"%")):"")+
      (oos.additionalCoverageNeeded===null?"":(
        " · نحتاج "+oos.additionalCoverageNeeded+
        " حالات بتغطية حقيقية إضافية عند ثبات العينة."))+
      (oos.reasonCounts?(
        " · نقص شموع بعد الإشارة: "+oos.reasonCounts.NO_POST_SIGNAL_BARS+
        "؛ حالات معلقة: "+oos.reasonCounts.PENDING_OR_UNFINISHED+
        (oos.reasonCountsExhaustive?" · التصنيف يغطي حالات النقص.":
          " · أسباب النقص غير مكتملة التصنيف.")):"")+
      (oos.sourceTimestampVerified?" · تاريخ المصدر موثق.":
       " · وقت مصدر التقييم غير موثق؛ المصدر بحثي فقط."):
      "لا يوجد تقرير مشروط صالح عن الاختبار خارج العينة؛ لا نستنتج نسبة نجاح.";
    put("terminal-oos-status",oosText);
    put("terminal-overview-warning",
      "مصدر الأسهم Yahoo بحثي؛ عمر تقرير الترشيحات: "+
      (age===null?"غير معروف":fmt(age,1)+" ساعة")+
      (stale?" · التحليلات التاريخية غير قابلة للتنفيذ الآن.":" · الترتيب لا يثبت صفقة ناجحة.")+
      " · أخبار التجميع غير رسمية · لا أسعار خيارات تنفيذية متحققة تلقائيًا.");
  }
  function renderFreeOptions(){
    const source=state.freeOptions;
    const panel=$("terminal-free-options-events");
    if(panel)panel.replaceChildren();
    if(!source){
      put("terminal-free-options-status",
        "لم يصل تقرير المصادر المجانية بعد. لا نعتبر غياب التقرير توفرًا للأسعار.");
      return;
    }
    const f=source.filingpulse||{},oi=source.occ_open_interest||{};
    const health=f.health_reachable===true?"FilingPulse يستجيب":"FilingPulse غير متاح";
    const filing=f.status==="THIRD_PARTY_RESEARCH_ONLY"?
      "وصلت إفصاحات عبر طرف ثالث ولم تُراجع مباشرة من SEC":
      f.status==="NO_API_KEY_HEALTH_ONLY"?
      "يلزم مفتاح FilingPulse المجاني لجلب الإفصاحات":
      "الإفصاحات غير متاحة: "+String(f.status||"غير محدد");
    const occ=oi.status==="HISTORICAL_DAILY_AGGREGATE"?
      "OCC فائدة مفتوحة تاريخية وليست أسعار تنفيذ":
      "OCC الفائدة المفتوحة: "+String(oi.status||"غير متاح");
    put("terminal-free-options-status",
      health+" · "+filing+" · "+occ+
      " · Tradier يحتاج حسابًا مخولًا ولا تُعرض أسعار حساب شخصي هنا.");
    if(!panel)return;
    const events=Array.isArray(f.events)?f.events.slice(0,6):[];
    for(const item of events){
      if(item.third_party_source!=="FILINGPULSE_SEC_DERIVED"||
         item.official_sec_api_response_verified!==false||
         item.option_execution_eligible!==false||
         !/^[A-Z][A-Z0-9.-]{0,8}$/.test(item.symbol||""))continue;
      const link=safeOfficial(item.source_url);
      if(!link)continue;
      const div=txt("article","","terminal-free-options-event");
      div.append(txt("strong",item.symbol+" · "+String(item.form||"إفصاح")+
        " · "+String(item.filed_date||"غير محدد")));
      const a=txt("a","مستند SEC المرتبط ↗");
      a.href=link;a.target="_blank";a.rel="noopener noreferrer";
      div.append(a,txt("small","رصد FilingPulse (طرف ثالث) وليس تأكيد SEC مباشر"+
        (Array.isArray(item.item_codes)&&item.item_codes.length?
          " · فقرات "+item.item_codes.join("، "):"")));
      panel.append(div);
    }
    if(!panel.children.length)panel.append(txt("p",
      "لا توجد أحداث مؤهلة للنشر؛ غيابها لا يثبت عدم وجود إفصاحات.",
      "terminal-empty"));
  }
  function renderStrength(){
    const score=$("terminal-strength-score"),breakdown=$("terminal-strength-breakdown");
    if(!score||!breakdown)return;
    breakdown.replaceChildren();
    const data=state.strength;
    if(!data){
      score.textContent="غير متاح / 100";
      put("terminal-strength-summary",
        "لا يوجد تقرير حديث صالح. لا نستنتج درجة من بيانات قديمة أو مفقودة.");
      return;
    }
    score.textContent=String(data.strength_score)+" / 100";
    put("terminal-strength-summary",
      "مؤشر جاهزية البيانات والتحقق البحثي · التقرير: "+
      stamp(data.generated_at)+
      " · ليس نسبة نجاح تداول ولا تقييمًا لجمال الواجهة.");
    const labels={
      charts:"الشارتات والفريمات",
      independent_prices:"استقلالية الأسعار",
      issuer_filings:"إفصاحات الشركات",
      options_market_data:"بيانات الخيارات",
      walk_forward:"الاختبار خارج العينة",
      feed_operations:"حداثة تشغيل المصادر"
    };
    for(const component of data.components){
      if(!Object.prototype.hasOwnProperty.call(labels,component.id))continue;
      const line=txt("div","","terminal-strength-line");
      const top=txt("div","","terminal-strength-line-top");
      top.append(txt("strong",labels[component.id]),
        txt("span",fmt(component.earned,2)+" / "+component.maximum));
      const track=txt("div","","terminal-strength-meter");
      const fill=txt("div","","terminal-strength-fill");
      fill.style.width=String(Math.max(0,Math.min(100,
        100*component.earned/component.maximum)))+"%";
      track.append(fill);line.append(top,track);
      breakdown.append(line);
    }
  }
  function optionsSummary(row){
    if(!row||row.status!=="OK")return null;
    const pct=x=>Number.isFinite(x)?fmt(100*x,1)+"%":"—";
    const em=row.expected_move,iv=row.atm_iv_term?.[0],sk=row.skew_25d;
    const oi=row.oi_concentration||{};
    return {
      headline:(em?"حركة متوقعة ±"+fmt(em.move_pct,2)+"% حتى "+em.expiry+" ("+fmt(em.range_low)+"–"+fmt(em.range_high)+")":
        "الحركة المتوقعة غير متاحة")+" · IV عند السعر "+(iv?pct(iv.atm_iv):"—"),
      details:[
        "انحراف 25 دلتا (بوت − كول): "+(sk?pct(sk.put_minus_call):"غير متاح"),
        "نسبة حجم البوت/الكول: "+(Number.isFinite(row.put_call_volume_ratio)?fmt(row.put_call_volume_ratio,2):"—"),
        "أعلى OI كول: "+((oi.call||[]).map(x=>fmt(x.strike)).join("، ")||"—")+
          " · أعلى OI بوت: "+((oi.put||[]).map(x=>fmt(x.strike)).join("، ")||"—")+" (جلسة سابقة)",
        "هيكل IV: "+((row.atm_iv_term||[]).slice(0,4).map(t=>t.expiry.slice(5)+" "+pct(t.atm_iv)).join(" · ")||"—"),
        "عقود سيولة جيدة (بحثي، غير تنفيذي): كول "+(row.liquid_contract_screen?.call?.length||0)+
          " · بوت "+(row.liquid_contract_screen?.put?.length||0)
      ].concat(["call","put"].flatMap(side=>(row.liquid_contract_screen?.[side]||[]).map(c=>
        (side==="call"?"CALL ":"PUT ")+fmt(c.strike)+" · "+c.expiry+" · دلتا "+fmt(c.delta,2)+
        " · سبريد "+fmt(c.spread_pct,1)+"% · OI "+fmt(c.oi,0))))
    };
  }
  function renderOptionsAnalytics(){
    const box=$("terminal-options-analytics");if(!box)return;
    box.replaceChildren();
    const report=state.optionsAnalytics;
    if(!report){put("terminal-options-analytics-status","لا يوجد تقرير تحليلات عقود منشور بعد.");return;}
    if(report.status==="SOURCE_TERMS_BLOCKED"){
      put("terminal-options-analytics-status","متوقف: "+String(report.reason_ar||"شروط المصدر تمنع الجلب الآلي")+
        " · التقرير: "+stamp(report.generated_at));return;}
    put("terminal-options-analytics-status","المصدر: "+report.source+" · التقرير: "+stamp(report.generated_at)+
      " · مؤجل وليس تنفيذيًا · لا تُنشر أسعار العقود الخام"+
      (Object.keys(report.errors||{}).length?" · تعذر: "+Object.keys(report.errors).join("، "):""));
    for(const [symbol,row] of Object.entries(report.symbols||{})){
      const view=optionsSummary(row);
      const item=txt("details","","terminal-structural-item");
      item.append(txt("summary",symbol+" · "+(view?view.headline:"بيانات غير متاحة")));
      for(const line of view?.details||[])item.append(txt("small",line,"terminal-structural-notice"));
      box.append(item);
    }
  }
  function renderOptions(){
    renderOptionsAnalytics();
    const target=$("terminal-options-readiness"),grid=$("terminal-options-breakdown");
    if(!target||!grid)return;grid.replaceChildren();
    const data=state.runtime?.option_provider_readiness;
    if(!data){
      put("terminal-options-readiness","لا يوجد تقرير جاهزية خيارات قابل للتحقق. لا يمكن اقتراح عقد قابل للتنفيذ.");
      return;
    }
    const ready=data.production_quote_ready===true&&data.production_flow_ready===true;
    put("terminal-options-readiness",ready?
      "أبلغ المصدر عن بيانات صالحة؛ يجب التأكد من كل عقد على حدة عبر بوابة V11.":
      "الوضع: "+String(data.status||"غير متاح")+
      " · عقود تنفيذية غير مؤهلة · اتجاه CALL/PUT بحثي فقط ولا توجد توصية عقد موثقة.");
    grid.append(
      pulse("سلاسل خيارات بحثية",String(data.usable_chains??"—"),
        "توجد بيانات لكنها ليست بالضرورة آنية"),
      pulse("سلاسل مصادر تنفيذية",String(data.live_primary_chains??"—"),
        "تتطلب تحققًا من Bid/Ask ووقت عرض السعر",data.live_primary_chains?"neutral":"caution"),
      pulse("مصادر مستقلة متقاطعة",String(data.cross_source_chains??"—"),
        "Yahoo وyfinance من عائلة واحدة"),
      pulse("سلاسل OPRA",String(data.opra_chains??"—"),
        "لا يتم اختراع OPRA من الأخبار أو OHLC")
    );
  }
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
    const stockInfo=state.watchCharts?.symbols?.[symbol];
    const stockSeries=stockInfo?.intervals;
    const volatility=stockInfo?.volatility_shadow;
    if(volatility?.available===true&&volatility.research_only===true&&
       volatility.independent_data_confirmation===false&&
       Number.isFinite(volatility.width_pct)&&
       typeof volatility.source_last_daily_bar==="string"){
      card.append(pair("بولنجر · انكماش بحثي",
        (volatility.compression_watch===true?"انكماش ملحوظ":"نطاق طبيعي")+
        " · "+fmt(volatility.width_pct,2)+"%"+
        " · جلسة "+volatility.source_last_daily_bar));
    }
    const confluence=stockInfo?.price_confluence;
    if(confluence?.research_only===true&&
       confluence.options_execution_eligible===false&&
       confluence.source_family==="yahoo"&&
       typeof confluence.source_last_daily_bar==="string"){
      const tags={
        BREAKOUT_AFTER_COMPRESSION:"اختراق بعد انكماش + حجم يومي",
        VOLUME_BREAKOUT_WATCH:"اختراق حجمي دون انكماش مؤكد",
        COMPRESSION_WATCH:"انكماش · ترقب حركة",
        NO_PATTERN:"لا نمط فني مكتمل"
      };
      card.append(pair("تلاقي إشارات السعر والحجم",
        String(tags[confluence.stage]||"غير متاح")+
        " · جلسة "+confluence.source_last_daily_bar));
      if(Number.isFinite(confluence.rvol_daily))
        card.append(pair("RVOL يومي من الشموع",fmt(confluence.rvol_daily,2)));
      const replay=confluence.historical_replay;
      if(replay?.lookahead_safe===true&&Number.isInteger(replay.matured_events))
        card.append(pair("تجارب تاريخية مكتملة (5 جلسات)",
          String(replay.matured_events)+" · لا تمثل نسبة نجاح"));
    }
    const media=stockInfo?.news_attention;
    if(media?.authority==="NEWS_SEARCH_ATTENTION_ONLY"&&
       media.official_catalyst_verified===false)
      card.append(pair("رصد اسم الشركة في الأخبار",
        "غير رسمي · "+stamp(media.latest_published_at)));
    card.append(pair("شموع يومية / 15 دقيقة",
      (stockSeries?.["1d"]?.bars?.length||0)+" / "+(stockSeries?.["15m"]?.bars?.length||0)));
    if(stockInfo?.historical_cache_only===true){
      card.append(pair("حالة الشارت","محفوظ سابقًا — غير محدث"));
    }else if(stockInfo?.has_retained_timeframes===true){
      card.append(pair("حالة الشارت","بعض الفريمات محفوظة من فحص سابق"));
    }
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
      state.watchCharts?"شارتات بها شموع مصدر خلال ٧ أيام (وليست أسعارًا لحظية): "+
        (state.watchCharts.coverage?.with_valid_charts||0)+" من "+
        (state.watchCharts.coverage?.requested||0)+" سهمًا مطلوبًا · "+
        "رموز بها شموع محفوظة: "+
        (state.watchCharts.coverage?.retained_symbols_count||0)+
        " (تاريخية فقط) · التقرير: "+
        stamp(state.watchCharts.generated_at):
        "لم تصل بيانات شارتات جديدة؛ لا نخترع شموعًا أو بيانات لحظية.");
    put(kind==="large"?"terminal-large-note":"terminal-small-note",
      (kind==="large"?"قائمة الشركات الكبيرة والمعروفة":"قائمة الشركات المضاربية/مرتفعة الحركة؛ لا يُحسم حجم الرسملة دون مصدر مستقل")+
      " · وقت فحص الأسهم: "+stamp(state.brief?.source_generated_at)+
      " · أسعار الرصد ليست حية · لا تُفسَّر الدرجة كنسبة ربح.");
  }
  function renderClassical(){
    const target=$("terminal-classical-list");if(!target)return;
    target.replaceChildren();
    const report=state.classical;
    const age=feedAgeHours(report?.source_generated_at);
    if(!report||age===null){
      put("terminal-classical-health","لا يوجد تحليل منشور بعد؛ يظهر بعد أول تحليل في الجلسة.");
      target.append(txt("p","لا توجد بيانات؛ لا يتم اختراع اتجاه.","terminal-empty"));
      return;
    }
    const c=report.counts||{};
    put("terminal-classical-health","آخر تحليل: "+stamp(report.source_generated_at)+
      " · CALL "+(c.CALL??0)+" · PUT "+(c.PUT??0)+" · انتظار "+(c.WAIT??0)+
      " · الحالة: "+String(report.operational_status||"غير معروف")+
      (age>2?" · التحليل ليس من الجلسة الحالية":""));
    const dirAr={BULLISH:"صاعد",BEARISH:"هابط",NEUTRAL:"محايد",UNAVAILABLE:"غير متاح"};
    const rows=report.companies.filter(r=>/^[A-Z][A-Z0-9.-]{0,9}$/.test(r?.symbol||""));
    for(const row of rows.slice(0,24)){
      const item=txt("article","","terminal-structural-item");
      const title=txt("div","","terminal-structural-title");
      const noTrade=row.trade_status==="NO_TRADE";
      const label=noTrade?(row.decision+" · لا تداول"):row.decision==="CALL"?"CALL · صعود":row.decision==="PUT"?"PUT · هبوط":"انتظار";
      title.append(txt("strong",row.symbol),chip(label,noTrade?"STALE":row.decision==="CALL"?"UP":row.decision==="PUT"?"DOWN":null));
      const tf=row.timeframes||{};
      item.append(title,
        pair("توافق الأطر",Number.isInteger(row.agreement_pct)?row.agreement_pct+"%":"غير متاح"),
        pair("يومي · ساعة · 15د",[tf.daily,tf.hourly,tf.intraday].map(v=>dirAr[v]||"غير متاح").join(" · ")),
        pair("آخر إغلاق مرجعي",fmt(row.reference_close,2)));
      if(row.decision!=="WAIT"){
        item.append(pair("التأكيد",fmt(row.confirmation_level,2)),pair("الإلغاء",fmt(row.invalidation_level,2)));
        if(row.targets){
          if(Number.isFinite(row.targets.entry))item.append(pair("دخول مشروط",fmt(row.targets.entry,2)));
          item.append(pair("الهدف 1 · الهدف 2",fmt(row.targets.t1,2)+" · "+fmt(row.targets.t2,2)));
          if(Number.isFinite(row.targets.t1_reward_to_risk))item.append(pair("العائد/المخاطرة النظري",fmt(row.targets.t1_reward_to_risk,2)));
        }
        if(noTrade)item.append(txt("small","لا تداول: العائد إلى المخاطرة حتى الهدف الأول أقل من 1.","terminal-structural-notice"));
      }
      for(const line of (row.scenarios_ar||[]).slice(0,3))item.append(txt("small",line,"terminal-structural-notice"));
      item.append(chartButton(row.symbol,"الشارت ↗"));
      target.append(item);
    }
    if(!rows.length)target.append(txt("p","لا توجد شركات في آخر تحليل.","terminal-empty"));
  }
  const STAGE_LABELS={PRESSURE_BUILDING:"ضغط يتكوّن",IGNITION:"بداية اشتعال",EXPLOSION:"انفجار"};
  function stageQualityLines(report){
    if(!report?.stages)return [];
    const pct=x=>Number.isFinite(x)?fmt(100*x,1)+"%":"—";
    return Object.entries(STAGE_LABELS).map(([key,label])=>{
      const s=report.stages[key];
      if(!s||!Number.isInteger(s.decisive)||s.decisive===0)return label+": لا توجد نتائج مكتملة بعد";
      const below=Number.isFinite(s.precision_direction)&&Number.isFinite(s.breakeven_hit_rate)&&
        s.precision_direction<s.breakeven_hit_rate;
      return label+": إصابة الاتجاه "+pct(s.precision_direction)+" مقابل تعادل "+pct(s.breakeven_hit_rate)+
        " · متوسط صافٍ بعد التكلفة "+(Number.isFinite(s.expectancy_net_pct)?fmt(s.expectancy_net_pct,2)+"%":"—")+
        " · حركة كبيرة بأي اتجاه "+pct(s.big_move_any_direction_rate)+
        " · عينة "+s.decisive+(s.verdict_sample_sufficient?"":" (غير كافية)")+
        (below?" · أقل من نقطة التعادل":"");
    });
  }
  const MODEL_AR={BASELINE_ALL_DAYS:"خط الأساس شراء (كل الأيام)",BASELINE_SHORT_ALL_DAYS:"خط الأساس بيع (كل الأيام)",BREAKOUT_VOLUME:"اختراق + فوليوم",
    RELATIVE_STRENGTH:"قوة نسبية",LIQUIDITY_EXPANSION:"توسع السيولة",GAP_CONTINUATION:"استمرار الفجوة",
    FAILED_BREAKOUT_REVERSAL:"انعكاس اختراق فاشل (بيع)",CATALYST_FLOAT:"محفز + فلوت",PREMARKET_MOMENTUM:"زخم ما قبل الافتتاح"};
  function modelLabLines(lab){
    if(!lab?.models)return [];
    const pct=x=>Number.isFinite(x)?fmt(100*x,1)+"%":"—";
    const net=x=>Number.isFinite(x)?fmt(x,2)+"%":"—";
    return Object.entries(lab.models).map(([key,m])=>{
      const name=MODEL_AR[key]||key;
      if(m.status==="NOT_TESTABLE")return name+": غير قابل للاختبار — "+String(m.reason||"");
      return name+": إصابة الهدف "+pct(m.all?.target_hit_rate)+" (تعادل "+pct(m.all?.breakeven_hit_rate)+")"+
        " · صافي بعد التكلفة "+net(m.all?.mean_net_pct)+
        " · النصف الأول "+net(m.early?.mean_net_pct)+" / الثاني "+net(m.late?.mean_net_pct)+
        " · عينة "+(m.all?.signals??0)+
        (key.startsWith("BASELINE_")?"":m.beats_baseline_both_halves_and_positive_late?" · يتفوق على خط أساس نفس الاتجاه":" · لا تفوق مثبت");
    });
  }
  function renderModelLab(box){
    const lab=state.modelLab;
    const item=txt("article","","terminal-structural-item");
    item.append(txt("strong","مختبر النماذج: قواعد مسجلة مسبقًا مقارنة بخط الأساس (بيانات تاريخية يومية)"));
    if(!lab){item.append(txt("small","لم يُنشر تقرير المختبر بعد.","terminal-structural-notice"));box.append(item);return;}
    for(const line of modelLabLines(lab))item.append(txt("small",line,"terminal-structural-notice"));
    for(const [label,spa] of [["نماذج الشراء مقابل خط أساس الشراء",lab.spa],["نماذج البيع مقابل خط أساس البيع",lab.spa_short]]){
      if(!spa)continue;
      item.append(txt("small",spa.status==="OK"?
        "اختبار SPA ("+label+"، مكتبة arch): p = "+fmt(spa.pvalue_consistent,3)+
          (spa.pvalue_consistent<0.05?" — تفوق نسبي على خط الأساس، وليس ربحية بالضرورة":" — لا دليل إحصائي على تفوق أي نموذج"):
        "اختبار SPA ("+label+") غير متاح: "+String(spa.status||"—")));
    }
    item.append(txt("small","الكون: "+String(lab.universe?.with_bars??"—")+" سهمًا مختارًا من سجل الرادار (تحيز اختيار مُعلن) · "+
      "الدخول عند افتتاح اليوم التالي · الشمعة التي تلمس الهدف والوقف معًا تُحسب خسارة · التقرير: "+stamp(lab.generated_at)));
    box.append(item);
  }
  function renderExplosionQuality(){
    const box=$("terminal-explosion-quality");if(!box)return;
    box.replaceChildren();
    const report=state.stageEval;
    if(!report){box.append(txt("p","لا يوجد تقييم منشور لجودة المراحل بعد.","terminal-empty"));renderModelLab(box);return;}
    const item=txt("article","","terminal-structural-item");
    item.append(txt("strong","جودة المراحل المقاسة على نتائج مكتملة (ليست احتمالات)"));
    for(const line of stageQualityLines(report))item.append(txt("small",line,"terminal-structural-notice"));
    item.append(txt("small","خط الأساس (كل الإشارات): "+
      (Number.isFinite(report.population?.pooled_direction_baseline)?
        fmt(100*report.population.pooled_direction_baseline,1)+"%":"—")+
      " · الحركة الكبيرة لا تعني صحة اتجاه الإشارة · التكاليف افتراضية حسب سعر السهم · التحديث: "+
      stamp(report.generated_at)));
    box.append(item);
    renderModelLab(box);
  }
  // Missing values always sort last; the published order is kept for ties.
  function sortCandidates(rows,key){
    const list=[...(rows||[])];
    if(key==="stage"||!key)return list;
    const ascending=key==="float_shares";
    return list.map((row,i)=>({row,i})).sort((a,b)=>{
      const x=a.row?.[key],y=b.row?.[key];
      const okX=Number.isFinite(x),okY=Number.isFinite(y);
      if(okX!==okY)return okX?-1:1;
      if(!okX||x===y)return a.i-b.i;
      return ascending?x-y:y-x;
    }).map(x=>x.row);
  }
  function renderExplosion(){
    renderExplosionQuality();
    const target=$("terminal-explosion-list");if(!target)return;
    target.replaceChildren();
    const report=state.explosion;
    const age=feedAgeHours(report?.source_generated_at);
    const counts=report?.stage_counts||{};
    if(!report||age===null){
      put("terminal-explosion-health","لا يوجد فحص منشور بعد؛ يظهر الرادار بعد أول فحص للسوق في الجلسة.");
      target.append(txt("p","لا توجد بيانات؛ لا يتم اختراع مرشحين.","terminal-empty"));
      return;
    }
    put("terminal-explosion-health","آخر فحص: "+stamp(report.source_generated_at)+
      " · ضغط "+(counts.PRESSURE_BUILDING??0)+" · اشتعال "+(counts.IGNITION??0)+
      " · انفجار "+(counts.EXPLOSION??0)+" · ممتد "+(counts.EXTENDED??0)+
      (age>2?" · الفحص ليس من الجلسة الحالية":""));
    const tone={PRESSURE_BUILDING:"STALE",IGNITION:"UP",EXPLOSION:"UP",EXTENDED:"DOWN"};
    const rows=sortCandidates(report.candidates.filter(r=>/^[A-Z][A-Z0-9.-]{0,9}$/.test(r?.symbol||"")),
      $("terminal-explosion-sort")?.value||"stage");
    for(const row of rows.slice(0,20)){
      const item=txt("article","","terminal-structural-item");
      const title=txt("div","","terminal-structural-title");
      title.append(txt("strong",row.symbol),chip(String(row.stage_ar||row.stage),tone[row.stage]||null));
      item.append(title,
        pair("ترتيب بحثي",fmt(row.score,1)+" / 100"),
        pair("حركة اليوم",Number.isFinite(row.day_move_pct)?fmt(row.day_move_pct,2)+"%":"غير متاح"),
        pair("RVOL بنفس الوقت",Number.isFinite(row.rvol_same_time)?
          fmt(row.rvol_same_time,2)+"× · "+(row.rvol_same_time_sessions||"—")+" جلسة مقارنة":"غير متاح"),
        pair("حجم اليوم حتى الآن ÷ متوسط يوم كامل",
          Number.isFinite(row.volume_vs_avg_day??row.rvol)?fmt(row.volume_vs_avg_day??row.rvol,2)+"×":"غير متاح"),
        pair("أسهم حرة",Number.isFinite(row.float_shares)?fmt(row.float_shares/1e6,2)+" مليون":"غير متاح"),
        pair("سيولة دولارية",Number.isFinite(row.dollar_volume)?fmt(row.dollar_volume/1e6,2)+" مليون $":"غير متاح"));
      if(row.catalyst_headline){const h=txt("p",String(row.catalyst_headline).slice(0,160));h.dir="auto";item.append(h);}
      const sec=row.official_catalyst_url?safeOfficial(row.official_catalyst_url):null;
      if(sec){const a=txt("a","إفصاح SEC الرسمي ↗","terminal-card-action");a.href=sec;a.target="_blank";a.rel="noopener noreferrer";item.append(a);}
      if(Number.isFinite(row.dilution_risk)&&row.dilution_risk>=50)
        item.append(txt("small","تحذير: مخاطر تخفيف ملكية مرتفعة","terminal-structural-notice"));
      if(row.stage==="EXTENDED")
        item.append(txt("small","الحركة ممتدة؛ الدخول المتأخر عالي المخاطر","terminal-structural-notice"));
      if(row.volume_flag==="PRESSURE_WITHOUT_SAME_TIME_VOLUME")
        item.append(txt("small","ضغط بلا حجم داعم: الحجم أقل من المعتاد لنفس الوقت؛ يحتاج تأكيدًا قبل اعتباره بناء ضغط","terminal-structural-notice"));
      target.append(item);
    }
    if(!rows.length)target.append(txt("p","لا توجد أسهم في مراحل الضغط أو الاشتعال في آخر فحص.","terminal-empty"));
  }
  function renderStructuralWatch(){
    const target=$("terminal-structural-list");if(!target)return;
    target.replaceChildren();
    const report=state.structural;
    const age=feedAgeHours(report?.source_observed_at);
    const valid=report?.status==="RESEARCH_SNAPSHOT" && age!==null && age<=7*24;
    const rows=valid?report.candidates:[];
    put("terminal-structural-health",valid?
      "فحص شمل "+fmt(report.universe_rows_screened,0)+" صفًا مدرجًا · "+
      rows.length+" مرشحًا بحثيًا · وقت الرصد الأصلي: "+stamp(report.source_observed_at)+
      " · البيانات ليست أسعارًا لحظية ولا تثبت محفزًا رسميًا":
      "لا يوجد فحص هيكلي حديث موثوق خلال 7 أيام؛ القائمة غير محدثة ولا تصلح للتوصية.");
    if(!rows.length){
      target.append(txt("p","لا توجد مرشحات حديثة صالحة؛ لا يتم اختراع بيانات بديلة.","terminal-empty"));
      return;
    }
    for(const row of rows){
      if(!/^[A-Z][A-Z0-9]{0,5}(?:[.-][A-Z])?$/.test(row?.symbol||"")||
          !Number.isFinite(row.market_cap_observed)||
          !Number.isFinite(row.structural_score_research))continue;
      const item=txt("article","","terminal-structural-item");
      const title=txt("div","","terminal-structural-title");
      title.append(txt("strong",row.symbol),chip("بحث هيكلي","STALE"));
      item.append(title,txt("p",String(row.name||row.symbol).slice(0,110)),
        pair("رسملة وقت الفحص",fmt(row.market_cap_observed/1e6,2)+" مليون $"),
        pair("أسهم حرة غير موثقة",Number.isFinite(row.float_shares_unverified)?
          fmt(row.float_shares_unverified/1e6,2)+" مليون":"غير متاح"),
        pair("درجة وصفية لا تعني ربحًا",fmt(row.structural_score_research,0)+" / 100"));
      const bars=state.watchCharts?.symbols?.[row.symbol]?.intervals?.["1d"]?.bars;
      if(Array.isArray(bars)&&bars.length>=2)item.append(chartButton(row.symbol,"فتح الشارت البحثي ↗"));
      else item.append(txt("small","لا يوجد شارت منشور؛ لا نفترض وجود دخول أو هدف.","terminal-structural-notice"));
      const risk=Array.isArray(state.sec?.filings)?state.sec.filings.find(f=>
        f.symbol===row.symbol&&f.original_filing_confirmed===true&&
        (f.event_type==="OFFERING_OR_DILUTION_REVIEW"||
         f.potential_dilution_review===true)):null;
      item.append(txt("small",risk?
        "تنبيه: إفصاح إصدار أو تخفيف يحتاج مراجعة.":
        "مخاطر الإصدارات والتخفيف غير محسومة؛ يلزم التحقق من الإفصاحات.",
        risk?"terminal-structural-risk":"terminal-structural-notice"));
      target.append(item);
    }
  }
  function newsCard(item,official){
    const card=txt("article","","terminal-news-item");
    const risky=item.event_type==="OFFERING_OR_DILUTION_REVIEW"||
      item.potential_dilution_review===true||
      item.event_topic==="RISK_OR_ADVERSE_EVENT_MENTION";
    card.append(chip(risky?"تحذير / مراجعة":official?"إفصاح أصلي":"خبر تجميعي",risky?"DOWN":null));
    const impact={HIGH:"أثر مرتفع",MEDIUM:"أثر متوسط",LOW:"أثر منخفض"}[item.impact_level];
    if(impact)card.append(chip(impact+" · قاعدة موثقة",item.impact_level==="HIGH"?"UP":null));
    card.append(txt("h5",official?
      String(item.symbol||"—")+" · "+String(item.form||"إفصاح"):
      String(item.symbol||"—")+" · "+String(item.headline||"عنوان غير متاح")));
    card.append(txt("p",official?
      "التاريخ: "+String(item.filing_date||"—")+" · "+String(item.event_type||"مراجعة"):
      "نُشر: "+stamp(item.published_at)+" · اتجاه الخبر غير مؤكد"));
    if(official){
      const topics={
        EARNINGS_RELEASE_REVIEW:"إعلان نتائج أعمال · لا نعرف إن تجاوز التوقعات",
        PERIODIC_FINANCIAL_REPORT_REVIEW:"تقرير مالي دوري · تحتاج الأرقام للمقارنة",
        UNREGISTERED_EQUITY_SALE_REVIEW:"مراجعة بيع أوراق مالية غير مسجلة · تحقق من الشروط",
        OFFERING_OR_REGISTRATION_TERMS_REVIEW:"مستند طرح أو تسجيل · لا يثبت إصدار أسهم جديد",
        MATERIAL_AGREEMENT_REVIEW:"اتفاق جوهري · الاتجاه السعري غير معلوم",
        DEBT_OBLIGATION_REVIEW:"التزامات مالية أو ديون · مراجعة المخاطر",
        MANAGEMENT_CHANGE_REVIEW:"تغييرات إدارية · مراجعة الحدث"
      };
      const evidence=Array.isArray(item.event_topics)?item.event_topics:[];
      for(const tag of evidence.slice(0,3)){
        if(Object.prototype.hasOwnProperty.call(topics,tag))
          card.append(txt("small",topics[tag],"terminal-news-topic"));
      }
      if(Array.isArray(item.eight_k_items)&&item.eight_k_items.length)
        card.append(txt("small","فقرات 8-K: "+item.eight_k_items.join("، "),"terminal-news-topic"));
    }
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
    const retries=Object.entries(feed?.source_cooldowns||{})
      .filter(([,meta])=>typeof meta?.retry_after==="string")
      .map(([key,meta])=>key+" بعد "+stamp(meta.retry_after)).slice(0,3);
    const secRetry=validDate(sec?.source_retry_after);
    put("terminal-news-status",
      "SEC: "+String(sec?.status||"غير متاح")+
      (secRetry!==null && secRetry>Date.now()?
        " · فحص SEC الرسمي التالي بعد "+stamp(sec.source_retry_after):"")+
      " · أخبار بحثية: "+stories.length+
      " · أحدث تقرير أخبار: "+stamp(feed?.generated_at)+
      (errors.length?" · أعطال موثقة: "+errors.slice(0,3).join("، "):"")+
      (retries.length?" · إعادة المحاولة التلقائية: "+retries.join("، "):"")+
      " · العنوان الإخباري لا يثبت قوة أثر الخبر."+
      (feed?.impact_policy?.version?" · مستوى الأثر تصنيف انتباه بقواعد ثابتة، ليس اتجاهًا ولا احتمالًا؛ الأخبار غير الرسمية لا تتجاوز «متوسط».":""));
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
  function plotCandles(bars,showEMA,levels,scenario=null,sessionVWAP=null){
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
      if(Number.isFinite(sessionVWAP)&&sessionVWAP>0&&
          typeof candle.createPriceLine==="function"){
        candle.createPriceLine({price:sessionVWAP,title:"VWAP جلسة · بحثي",
          color:"#D6B46B",lineWidth:2,lineStyle:2,axisLabelVisible:true});
      }
      if(scenario?.activation&&scenario?.invalidation){
        for(const [price,title,color] of [
          [scenario.activation,"تفعيل بحثي","#D8B66C"],
          [scenario.invalidation,"إبطال","#E37E8A"],
          [scenario.target1,"T1 بحثي","#65CDB2"],
          [scenario.target2,"T2 بحثي","#72ADDB"]]){
          if(typeof candle.createPriceLine==="function"&&
             typeof price==="number"&&Number.isFinite(price)&&price>0){
            candle.createPriceLine({price,title,color,lineWidth:1,lineStyle:2,axisLabelVisible:true});
          }
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
    // Classical-direction companies are alert targets (?chart= links), so
    // they must be selectable even without published chart bars.
    const classical=(state.classical?.companies||[]).map(x=>x?.symbol)
      .filter(s=>typeof s==="string"&&/^[A-Z][A-Z0-9.-]{0,9}$/.test(s));
    // Explosion candidates receive alert links too.
    const boom=(state.explosion?.candidates||[]).map(x=>x?.symbol)
      .filter(s=>typeof s==="string"&&/^[A-Z][A-Z0-9.-]{0,9}$/.test(s));
    const known=[...new Set([...INDEX_ORDER,...LARGE,...VOLATILE,
      ...discoveries,...watched,...fallback,...classical,...boom])];
    // A ?chart= symbol waits for the first full feed load before it can be
    // judged unknown; otherwise the early fallback would overwrite it.
    const pending=state.pendingSymbol&&known.includes(state.pendingSymbol)?state.pendingSymbol:null;
    select.replaceChildren();
    for(const symbol of known){
      const option=txt("option",symbol+" · "+(I_NAMES[symbol]||"سهم"));
      option.value=symbol;select.append(option);
    }
    state.symbol=pending||(known.includes(current)?current:"SPX");select.value=state.symbol;
  }
  const putMetric=(label,value)=>{
    const d=txt("div",""),p=txt("small",label),v=txt("strong",value);
    d.append(p,v);return d;
  };
  function renderEvidence(input){
    const wrap=$("terminal-evidence-grid");
    if(wrap)wrap.replaceChildren();
    if(typeof GhaziEvidence==="undefined"){
      put("terminal-evidence-status","غير متاح");
      put("terminal-evidence-summary","لم تُحمّل أداة التحقق البحثية.");
      return;
    }
    const result=GhaziEvidence.evaluate(input);
    put("terminal-evidence-status",result.label);
    put("terminal-evidence-summary",result.summary);
    if(!wrap)return;
    for(const check of result.checks){
      const card=txt("article","","terminal-evidence-item "+check.state);
      card.append(txt("strong",check.label),txt("p",check.detail));
      wrap.append(card);
    }
  }
  async function renderChart(){
    refreshSymbols();
    const symbol=state.symbol,tf=state.tf;
    // The summary uses published engine feeds, not candles, so it renders
    // even when this symbol has no chart bars.
    renderDecisionCard(symbol);
    const indexFrame=state.charts?.symbols?.[symbol]?.intervals?.[tf];
    const stockFrame=state.watchCharts?.symbols?.[symbol]?.intervals?.[tf];
    const frame=indexFrame||stockFrame;
    const stock=state.stockCharts?.charts?.[symbol];
    const usingStock=!frame&&!INDEX_ORDER.includes(symbol)&&tf==="1d"&&stock;
    const rows=uniqueValidBars(frame?.bars||(usingStock?stock.bars:[]));
    const levels=INDEX_ORDER.includes(symbol)?state.quotes?.symbols?.[symbol]?.levels?.last_completed_session:null;
    const select=$("terminal-chart-timeframe");
    const hasFrame=value=>Boolean(state.charts?.symbols?.[symbol]?.intervals?.[value] ||
      state.watchCharts?.symbols?.[symbol]?.intervals?.[value] ||
      (value==="1d"&&state.stockCharts?.charts?.[symbol]));
    if(select){
      for(const option of select.options)option.disabled=!hasFrame(option.value);
    }
    document.querySelectorAll("[data-terminal-tf]").forEach(button=>{
      const available=hasFrame(button.dataset.terminalTf);
      button.disabled=!available;
      const pressed=state.tf===button.dataset.terminalTf;
      button.classList.toggle("active",pressed);
      button.setAttribute("aria-pressed",String(pressed));
      button.title=available?"عرض شموع مكتملة":"لا توجد شموع فعلية متاحة لهذا الفريم";
    });
    const metric=$("terminal-chart-levels");if(metric)metric.replaceChildren();
    const decisionGrid=$("terminal-decision-levels");if(decisionGrid)decisionGrid.replaceChildren();
    if(rows.length<2){
      renderEvidence({bars:rows,frame,generatedAt:null,timeframe:tf});
      put("terminal-decision-state","غير متاح");
      put("terminal-decision-explain","لا توجد شموع كافية؛ لا يمكن تحديد اتجاه CALL / PUT أو أهداف.");
      clearPlot();
      put("terminal-chart-spot","—");put("terminal-chart-direction","لا توجد شموع OHLC منشورة");
      put("terminal-chart-date","—");
      put("terminal-chart-reading","لا توجد شموع مكتملة لهذا الرمز/الفريم في التقرير المتاح. لا نرسم شارتًا تقديريًا. "+
        (!INDEX_ORDER.includes(symbol)?"فريمات الأسهم تعتمد على توفر المصدر وقد تختفي أو تتأخر.":"المؤشرات تحتاج نشر ملف شموع المؤشرات."));
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
    const vwapShadow=stockFrame?.session_vwap;
    const validVWAP=vwapShadow?.available===true &&
      vwapShadow.research_only===true &&
      vwapShadow.source_family==="yahoo" &&
      vwapShadow.options_execution_eligible===false &&
      Number.isFinite(vwapShadow.value)&&vwapShadow.value>0 &&
      vwapShadow.source_last_bar_start===frame?.provider_bar_start_or_date;
    if(validVWAP){
      metric?.append(putMetric("VWAP جلسة · بحثي",
        fmt(vwapShadow.value)+" · "+String(vwapShadow.session_date||"غير محدد")));
    }
    const priceWatch=state.watchCharts?.symbols?.[symbol]?.price_confluence;
    if(tf==="1d"&&priceWatch?.research_only===true&&
       priceWatch.options_execution_eligible===false&&
       typeof priceWatch.source_last_daily_bar==="string"){
      metric?.append(putMetric("تلاقي الشموع والحجم (بحثي)",
        String(({BREAKOUT_AFTER_COMPRESSION:"اختراق بعد انكماش وحجم",
          VOLUME_BREAKOUT_WATCH:"اختراق حجمي",
          COMPRESSION_WATCH:"انكماش مرصود",
          NO_PATTERN:"لا نمط مكتمل"})[priceWatch.stage]||"غير متاح")+
        " · "+priceWatch.source_last_daily_bar));
      const replay=priceWatch.historical_replay;
      if(replay?.lookahead_safe===true&&Number.isInteger(replay.matured_events))
        metric?.append(putMetric("تجارب تاريخية مكتملة",
          String(replay.matured_events)+" (ليست نسبة نجاح)"));
    }
    const shadow=state.watchCharts?.symbols?.[symbol]?.volatility_shadow;
    if(tf==="1d"&&shadow?.available===true&&shadow.research_only===true&&
       shadow.independent_data_confirmation===false&&
       Number.isFinite(shadow.width_pct)){
      metric?.append(putMetric("بولنجر يومي (بحثي)",
        (shadow.compression_watch===true?"انكماش ملحوظ":"نطاق طبيعي")+
        " · "+fmt(shadow.width_pct,2)+"%"+
        " · "+String(shadow.source_last_daily_bar||"تاريخ غير محدد")));
    }
    const engine=typeof GhaziResearch!=="undefined"?GhaziResearch:null;
    const hourFrame=INDEX_ORDER.includes(symbol)?
      state.charts?.symbols?.[symbol]?.intervals?.["1h"]:
      state.watchCharts?.symbols?.[symbol]?.intervals?.["1h"];
    const sourceDate=INDEX_ORDER.includes(symbol)?state.charts?.generated_at:
      stockFrame?state.watchCharts?.generated_at:state.stockCharts?.generated_at;
    const ageHours=feedAgeHours(sourceDate);
    const currentConfirmed=frame?.current_session_confirmed===true &&
      ageHours!==null&&ageHours<=24;
    const scenario=engine?.analyze(rows,{
      hourBars:hourFrame?.bars,
      current_session_confirmed:currentConfirmed
    })||null;
    const side=scenario?.status==="HISTORICAL"?
      "لقطة تاريخية · "+(scenario.historical_side||"WAIT"):
      scenario?.status==="CONFLICT"?"WAIT · تعارض فريمات":
      scenario?.side==="CALL"?"CALL بحثي":
      scenario?.side==="PUT"?"PUT بحثي":"WAIT / لا تداول";
    put("terminal-decision-state",side);
    put("terminal-decision-explain",(scenario?.reason_ar||"تعذر إجراء تحليل مستقل.")+
      " · الاتجاه: "+String(scenario?.technical_bias||"غير متاح")+
      " · فريم الساعة: "+String(scenario?.hour_bias||"غير متاح")+
      " · لا تمثل هذه المستويات أوامر شراء أو عقود خيارات تنفيذية.");
    if(decisionGrid&&scenario){
      for(const [label,val] of [
        ["مقاومة 20 شمعة سابقة",scenario.resistance],
        ["دعم 20 شمعة سابقة",scenario.support],
        ["التفعيل المشروط",scenario.activation],
        ["إبطال السيناريو",scenario.invalidation],
        ["T1 | ATR14",scenario.target1],
        ["T2 | 2 × ATR14",scenario.target2]]){
        decisionGrid.append(putMetric(label,fmt(val)));
      }
    }
    renderEvidence({
      bars:rows,scenario,frame,timeframe:tf,generatedAt:sourceDate,
      confluence:state.watchCharts?.symbols?.[symbol]?.price_confluence,
      newsAttention:state.watchCharts?.symbols?.[symbol]?.news_attention
    });
    plotCandles(rows,state.ema,levels,scenario,validVWAP?vwapShadow.value:null);
    const currentClose=last.close;
    put("terminal-chart-scenario",range!==null && Number.isFinite(range)?
      "سيناريو نطاق الحركة بـ ATR (ليس احتمالًا): إذا استمر الزخم، "+
      "±1 ATR: "+fmt(currentClose-range)+" إلى "+fmt(currentClose+range)+
      " · ±2 ATR: "+fmt(currentClose-2*range)+" إلى "+fmt(currentClose+2*range)+
      ". الاتجاه الفني "+(STATES[bias]||"غير كافٍ")+
      "؛ السيناريو لا يراعي الأخبار أو الفجوات المستقبلية، ولا يمثل توقع Gamma.":
      "لا يمكن حساب نطاق ATR موثوق لهذا الشارت؛ تحتاج 15 شمعة على الأقل.");
    renderGamma(symbol);
    renderLiquidity(symbol);
    const current=frame?.current_session_confirmed===true;
    const retainedBar=frame?.historical_cache_only===true;
    const freshnessText=retainedBar?
      "شموع محفوظة من فحص سابق بتاريخ "+stamp(frame.cached_source_generated_at)+
      "؛ البيانات غير محدثة وليست سعرًا حاليًا":
      isDaily?"شارت جلسات يومية مكتملة (وليس سعرًا لحظيًا)":
      current?"شموع الجلسة الحالية مكتملة لكن المصدر غير مرخّص لحظيًا":
      "شموع مكتملة من جلسة قديمة/متأخرة، لا تستخدمها كسعر مباشر";
    const context=bias==="UP"?"السعر أعلى EMA20 وEMA50 مع RSI داعم للصعود":
      bias==="DOWN"?"السعر دون EMA20 وEMA50 مع RSI ضعيف":
      "اتجاه المتوسطات والـRSI غير متوافق أو لا توجد عينة كافية";
    put("terminal-chart-reading",symbol+" · "+(tf==="1d"?"يومي":tf)+
      (tf==="1h"?" · فريم الساعة مُجمّع من أربع شموع 15 دقيقة مكتملة؛ ليس سعرًا لحظيًا":"")+
      (tf==="4h"?" · فريم 4 ساعات مُجمّع من شموع 15 دقيقة مكتملة (09:30–13:30 و13:30–16:00 نيويورك)؛ لا يُعرض إلا مكتملًا":"")+
      " · "+context+" · نطاق آخر 20 شمعة "+fmt(low)+"–"+fmt(high)+
      " · "+freshnessText+". "+
      "التحليل وصفي ولا يتنبأ باحتمال الربح. مصدر الشموع: "+
      (stockFrame?"مراقبة الأسهم Yahoo — إنشاء التقرير: "+stamp(state.watchCharts?.generated_at):
       usingStock?"الرادار Yahoo — تاريخ التقرير: "+stamp(state.stockCharts?.generated_at):
       "Yahoo / yfinance — إنشاء التقرير: "+stamp(state.charts?.generated_at))+".");
  }
  const LIQ_WORDS={
    volume:{HIGH:"مرتفع",NORMAL:"طبيعي",LOW:"منخفض"},
    position:{ABOVE:"فوق",BELOW:"تحت",AT:"عند",INSIDE:"داخل"},
    breakout:{BREAKOUT_VOLUME_CONFIRMED:"اختراق قمة الأمس بحجم مرتفع",
      BREAKOUT_VOLUME_UNCONFIRMED:"اختراق قمة الأمس بحجم غير كافٍ",
      BREAKDOWN_VOLUME_CONFIRMED:"كسر قاع الأمس بحجم مرتفع",
      BREAKDOWN_VOLUME_UNCONFIRMED:"كسر قاع الأمس بحجم غير كافٍ",
      FAILED_BREAKOUT:"اختراق فاشل لقمة الأمس",FAILED_BREAKDOWN:"كسر فاشل لقاع الأمس"},
    sweep:{ABOVE_PRIOR_HIGH_REJECTED:"تجاوز قمة الأمس ثم ارتداد",
      BELOW_PRIOR_LOW_REJECTED:"تجاوز قاع الأمس ثم ارتداد"}
  };
  function liquidityView(map,symbol,now=Date.now()){
    const row=map?.symbols?.[symbol];
    if(!row)return {status:"غير متاح لهذا الرمز",metrics:[],note:"لا يغطي ملف السيولة هذا الرمز حاليًا."};
    if(row.status!=="OK")return {status:"شموع غير كافية",metrics:[],note:"لا توجد شموع 15 دقيقة مكتملة كافية."};
    const t=validDate(map.generated_at);
    const ageH=t===null?null:(now-t)/3600000;
    const stale=ageH===null||ageH>36;
    const vol=row.volume;
    const prof=row.profile_session;
    const metrics=[
      ["الحجم النسبي (نفس الوقت)",vol?(LIQ_WORDS.volume[vol.state]||"—")+" · RVOL "+fmt(vol.rvol,2):"عينة غير كافية"],
      ["VWAP الجلسة (تقريبي)",Number.isFinite(row.session_vwap)?
        fmt(row.session_vwap)+" · السعر "+(LIQ_WORDS.position[row.vwap_position]||"—"):"غير متاح"],
      ["POC / VAH / VAL (تقدير)",prof?fmt(prof.poc)+" / "+fmt(prof.vah)+" / "+fmt(prof.val):"غير متاح"],
      ["نطاق الافتتاح 30د",row.opening_range?
        fmt(row.opening_range.low)+"–"+fmt(row.opening_range.high)+" · "+
        (LIQ_WORDS.position[row.opening_range.status]||"—"):"غير مكتمل"],
      ["قمة/قاع الأمس",row.prior_day?fmt(row.prior_day.high)+" / "+fmt(row.prior_day.low):"غير متاح"],
      ["الاختراق",LIQ_WORDS.breakout[row.breakout]||"لا اختراق لنطاق الأمس"],
      ["سحب سيولة (استنتاج سعري)",LIQ_WORDS.sweep[row.sweep_proxy]||"لا يوجد"],
      ["فجوة الافتتاح",Number.isFinite(row.gap_pct)?fmt(row.gap_pct,2)+"%":"غير متاح"]];
    const reading=Array.isArray(row.reading_ar)?row.reading_ar.join(" "):"";
    return {
      status:(stale?"قديمة · ":"")+"جلسة "+String(row.session_date||"غير محددة"),
      metrics,
      note:reading+" آخر شمعة مكتملة: "+String(row.last_bar_start||"غير محدد")+
        " · إنشاء الملف: "+stamp(map.generated_at)+
        (stale?" · الملف أقدم من 36 ساعة ولا يمثل الجلسة الحالية.":"")
    };
  }
  function renderDecisionCard(symbol){
    const body=$("terminal-decision-card-body");if(!body)return;
    body.replaceChildren();
    const api=typeof GhaziDecision!=="undefined"?GhaziDecision:null;
    if(!api){put("terminal-decision-card-verdict","غير متاح");return;}
    let card;
    try{
      card=api.build(symbol,{index:state.quotes,classical:state.classical,liquidity:state.liquidity,
        news:state.news,explosion:state.explosion,gamma:state.gamma,options:state.optionsAnalytics,tracking:state.tracking});
    }catch{put("terminal-decision-card-verdict","تعذر بناء الخلاصة");return;}
    put("terminal-decision-card-verdict",card.verdictAr+" · "+card.evidenceBalance);
    const group=(title,items,empty)=>{
      const box=txt("div","","terminal-decision-group");
      box.append(txt("strong",title));
      const list=txt("ul","");
      for(const item of items.length?items:[empty])list.append(txt("li",item));
      box.append(list);body.append(box);
    };
    group("لماذا توجد قراءة؟",card.why,"لا توجد أسباب منشورة لهذا الرمز.");
    group("أدلة داعمة",card.support,"لا توجد أدلة داعمة متاحة.");
    group("أدلة معارضة",card.contra,"لا توجد أدلة معارضة ظاهرة في المصادر المتاحة.");
    if(card.context.length)group("سياق (لا يحدد الاتجاه)",card.context,"");
    const L=card.levels;
    group("الدخول المشروط والأهداف والإلغاء",L?[
      "دخول مشروط: "+fmt(L.entry),"T1: "+fmt(L.t1)+" · T2: "+fmt(L.t2),
      "إلغاء: "+fmt(L.invalidation),
      "عائد/مخاطرة حتى T1: "+(Number.isFinite(L.rr)?fmt(L.rr,2)+" (نظري)":"غير متاح")]:[],
      "لا توجد مستويات منشورة.");
    if(card.tracking)group("المتابعة: إشارات الرادار السابقة ونتائجها",
      [card.tracking.totals,...card.tracking.recent],"");
    group("حداثة البيانات",card.freshness.map(f=>f.label+": "+
      (f.ageHours===null?"وقت غير معروف":"قبل "+fmt(f.ageHours,1)+" ساعة")+(f.fresh?"":" · قديمة")),
      "لا توجد مصادر بتوقيت معروف.");
  }
  function renderLiquidity(symbol){
    const grid=$("terminal-liquidity-metrics");if(grid)grid.replaceChildren();
    const view=liquidityView(state.liquidity,symbol);
    put("terminal-liquidity-status",view.status);
    for(const [label,value] of view.metrics)grid?.append(putMetric(label,value));
    put("terminal-liquidity-note",view.note);
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
    const view=gammaView(data,symbol);
    put("terminal-gamma-status",view.status);
    for(const [label,value] of view.metrics)grid?.append(putMetric(label,value));
    put("terminal-gamma-note",view.note);
  }
  // Measured inputs vs model outputs are labelled separately; the engine's
  // levels are a Black-Scholes model on delayed Cboe data, never dealer books.
  function gammaView(data,symbol){
    const metrics=data?.metrics||{};
    const val=(key)=>metrics[key]?.count>0 &&
      Number.isFinite(metrics[key]?.median)?metrics[key].median:null;
    const gexSources=Number.isInteger(data?.independent_numerical_gex_sources)?
      data.independent_numerical_gex_sources:(metrics.gex?.count||0);
    const engine=data?.integrated_engines?.ghazi_gex_multi;
    const reading=data?.integrated_engines?.interpretation;
    const check=data?.integrated_engines?.level_validation;
    const modelled=engine?.available===true&&engine.provenance?.levels==="MODEL_ESTIMATED";
    const n=(x,p=0)=>Number.isFinite(x)?fmt(x,p):"غير متاح";
    const dist=x=>Number.isFinite(x)?" ("+(x>0?"+":"")+fmt(x,2)+"%)":"";
    const out=[];
    if(modelled){
      out.push(["SPX (مُقاس · Cboe مؤخر)",n(engine.spot,2)]);
      out.push(["Gamma Flip (نموذج)",n(engine.gamma_flip)+dist(reading?.distance_pct?.gamma_flip)]);
      out.push(["Call Wall (نموذج)",n(engine.call_wall)+dist(reading?.distance_pct?.call_wall)]);
      out.push(["Put Wall (نموذج)",n(engine.put_wall)+dist(reading?.distance_pct?.put_wall)]);
      out.push(["نظام الجاما (نموذج)",engine.gamma_regime==="positive"?"موجب · يهدئ الحركة":
        engine.gamma_regime==="negative"?"سالب · قد يضخم الحركة":"غير محدد"]);
      out.push(["ضغط التحوط لكل 1% (نموذج)",Number.isFinite(reading?.hedging_pressure_bn_per_1pct)?
        fmt(reading.hedging_pressure_bn_per_1pct,1)+" مليار $":"غير متاح"]);
      out.push(["تركيز الجاما GCI",Number.isFinite(engine.gci)?fmt(100*engine.gci,1)+"%":"غير متاح"]);
      out.push(["الانتهاءات المستخدمة",String(engine.expirations_used??"—")+" · الأقرب "+String(engine.front_expiry||"—")]);
    }else{
      for(const [label,key] of [["GEX بحثي (وحدة المصدر)","gex"],["Gamma Flip","flip"],
        ["Call Wall","call_wall"],["Put Wall","put_wall"]])
        out.push([label,val(key)===null?"غير متاح":fmt(val(key),1)]);
    }
    const tested=Number.isInteger(check?.sessions_tested)?check.sessions_tested:0;
    const validation=!check?"اختبار فائدة المستويات: غير متاح.":
      check.verdict==="INSUFFICIENT_SAMPLE"?
        "اختبار فائدة المستويات: "+tested+" جلسة من "+check.minimum_sessions_for_verdict+" مطلوبة؛ لا حكم بعد.":
        "اختبار فائدة المستويات على "+tested+" جلسة: احتواء الجدارين للنطاق "+
        fmt(100*check.walls_contained_range_rate,1)+"% مقابل نطاق بنفس العرض حول السعر "+
        fmt(100*check.same_width_centred_band_rate,1)+"% · "+
        (check.verdict==="WALLS_BEAT_BASELINE"?"الجداران أفضل من الخط الأساسي":"لا أفضلية على الخط الأساسي")+".";
    const lines=Array.isArray(reading?.reading_ar)?reading.reading_ar.slice(0,6).join(" "):"";
    return {
      status:modelled?"نموذج تقديري · SHADOW":gexSources<2?
        "SHADOW — جاما من مصدر رقمي واحد أو بلا بيانات":"SHADOW — توافق تجريبي غير معتمد",
      metrics:out,
      note:(modelled?lines+" ":engine?.status==="SOURCE_TERMS_BLOCKED"?
          "محرك جاما متوقف: "+String(engine.reason_ar||"")+". ":"لا توجد سلسلة عقود صالحة للمحرك. ")+validation+
        " · مُقاس: السعر وIV (مؤخر) وOI (جلسة سابقة) · نموذج: GEX والانقلاب والجدران والتحوط."+
        " · "+(symbol==="SPY"?"هذه مستويات SPX وليست قيم خيارات SPY. ":"")+
        "لا تثبت الأرقام تمركز صانع السوق أو اتجاه الغد. التقرير: "+stamp(data?.generated_at)+"."
    };
  }
  const HUB_FRESH={FRESH:"حديث",STALE:"قديم",MISSING:"غير منشور",UNTIMED:"بلا وقت موثق",FUTURE_TIMESTAMP:"وقت مستقبلي مرفوض"};
  const HUB_LICENSE={DERIVED_PUBLIC:"قيم مشتقة",FALLBACK_LABELLED:"مصدر احتياطي غير مرخص للأتمتة",
    OFFICIAL_PUBLIC:"مصدر رسمي/مسموح",INTERNAL_METRIC:"قياس داخلي",TERMS_RESTRICTED:"شروط المزود تقيد الاستخدام",
    MIXED_HEADLINES_AND_OFFICIAL:"إصدارات رسمية + عناوين بحث"};
  const HUB_RIGHTS={BLOCKED_PENDING_PERMISSION:"متوقف حتى الإذن",RESTRICTED:"مقيد",
    NOT_AUTHORISED_FALLBACK:"غير مصرح (احتياطي)",OK_FOR_STATED_USE:"مسموح للاستخدام المذكور",UNKNOWN:"غير معروف"};
  function hubLines(hub){
    if(!Array.isArray(hub?.datasets))return [];
    return hub.datasets.map(d=>({
      title:String(d.title_ar||d.file),
      tone:d.freshness==="FRESH"&&d.validation==="PASS"?"UP":d.freshness==="MISSING"?null:"DOWN",
      status:(HUB_FRESH[d.freshness]||d.freshness)+(d.validation==="FAIL"?" · فشل التحقق":""),
      rights:HUB_RIGHTS[d.rights_status]||"غير معروف",
      detail:"المصدر: "+String(d.source||"—")+" · "+(HUB_LICENSE[d.license_class]||d.license_class)+
        " · حق الاستخدام: "+(HUB_RIGHTS[d.rights_status]||"غير معروف")+
        " · العمر: "+(Number.isFinite(d.age_minutes)?fmt(d.age_minutes/60,1)+" ساعة":"—")+
        " · الإيقاع المتوقع: "+fmt(d.cadence_min,0)+" د · "+String(d.limitations||"")
    }));
  }
  function renderDataHub(){
    const box=$("terminal-data-hub");if(!box)return;
    box.replaceChildren();
    const hub=state.dataHub;
    if(!hub){put("terminal-data-hub-status","لا يوجد كتالوج بيانات منشور بعد.");return;}
    const f=hub.summary?.freshness||{};
    put("terminal-data-hub-status","مجموعات البيانات: "+(hub.summary?.total??"—")+
      " · حديثة "+(f.FRESH||0)+" · قديمة "+(f.STALE||0)+" · غير منشورة "+(f.MISSING||0)+
      " · فشل تحقق "+(hub.summary?.validation_failures??0)+
      " · مصادر احتياطية: "+((hub.summary?.fallback_sources||[]).join("، ")||"لا يوجد")+
      " · الكتالوج: "+stamp(hub.generated_at)+" · الأوقات من الملفات نفسها وليست أوقات أسعار."+
      " · الحداثة لا تعني صحة البيانات ولا حق نشرها؛ حق الاستخدام معروض لكل مصدر على حدة.");
    for(const line of hubLines(hub)){
      const item=txt("article","","terminal-structural-item");
      const head=txt("div","","terminal-structural-title");
      head.append(txt("strong",line.title),chip(line.status,line.tone));
      item.append(head,txt("small",line.detail,"terminal-structural-notice"));
      box.append(item);
    }
  }
  function renderTrust(){
    const wrap=$("terminal-trust-grid");if(!wrap)return;
    wrap.replaceChildren();
    const report=state.trust,runtime=state.runtime,audit=state.audit;
    const trustTime=validDate(report?.generated_at);
    const now=Date.now();
    const trustAge=trustTime===null?null:Math.max(0,Math.round((now-trustTime)/60000));
    const reportCurrent=trustAge!==null&&trustAge<=720;
    const sources=Array.isArray(report?.sources)?report.sources:[];
    const status=runtime?.option_provider_readiness;
    const executionReady=status?.production_quote_ready===true &&
      status?.production_flow_ready===true;
    put("terminal-trust-summary",
      "فحص المصادر: "+(trustTime===null?"غير متاح":stamp(report.generated_at))+
      (trustAge===null?"":" · عمر التقرير "+trustAge+" دقيقة")+
      (reportCurrent?"":" · التقرير غير حديث / لا يوجد تحقق حديث")+
      " · المصادر الرسمية المتحققة: "+(reportCurrent?report.official_sources_ok:"غير متاح")+
      "/"+(reportCurrent?report.official_sources_total:"—")+
      " · عقود الخيارات: "+(executionReady?"جاهزية المصدر مُعلنة وتحتاج تحققًا من العقد":"بحثية فقط — لا توجد أسعار تنفيذية متحققة")+
      " · هذا القسم لا يمنح أي مصدر صلاحية إصدار توصية تنفيذية.");
    if(!reportCurrent){
      wrap.append(txt("p","لا يوجد تقرير حديث اجتاز التحقق من محتوى المصادر. لا نعتبر الروابط الناجحة دليلًا على صحة الأسعار.","terminal-empty"));
    }
    const audited=Number.isInteger(audit?.coverage?.records)?
      audit.coverage.records:0;
    const covered=Number.isInteger(audit?.coverage?.covered_60m)?
      audit.coverage.covered_60m:0;
    const auditTime=validDate(audit?.generated_at);
    const auditRecent=auditTime!==null&&auditTime<=now+300000&&now-auditTime<=72*3600000;
    const coveragePct=audited>0&&covered<=audited?
      fmt(100*covered/audited,1)+"%":"غير متاح";
    // Signals whose 60m horizon ends after the regular close cannot be
    // measured at 60m; show the applicable figure beside the unadjusted one.
    const afterClose=Number.isInteger(audit?.coverage?.coverage_60m_not_applicable_after_close)?
      audit.coverage.coverage_60m_not_applicable_after_close:0;
    const preOpen=Number.isInteger(audit?.coverage?.coverage_60m_not_applicable_before_open)?
      audit.coverage.coverage_60m_not_applicable_before_open:0;
    const notApplicable=afterClose+preOpen;
    const applicable=audited-notApplicable;
    const applicablePct=notApplicable>0&&applicable>0&&covered<=applicable?
      fmt(100*covered/applicable,1)+"%":null;
    const verifiedV2=Number.isInteger(audit?.close_time_integrity?.verified_version_2_records)?
      audit.close_time_integrity.verified_version_2_records:0;
    for(const feed of [
      ["شارتات الأسهم",state.watchCharts?.generated_at,
        String(state.watchCharts?.coverage?.with_valid_charts??"—")+" سهم · Yahoo بحثي"],
      ["شارتات المؤشرات",state.charts?.generated_at,
        String(state.charts?.coverage?.symbols??"—")+" مؤشرات وصناديق · Yahoo بحثي"],
      ["الأخبار",state.news?.generated_at,"مصادر أخبار ومطابقة اسم الشركة · بحثي"],
      ["SEC",state.sec?.generated_at,
        "إفصاحات مؤكدة: "+String(state.sec?.coverage?.filings_verified??0)+
        " · الحالة: "+String(state.sec?.status||"غير متاح")],
      ["Gamma",state.gamma?.generated_at,
        "SHADOW فقط · GEX رقمي مستقل: "+String(state.gamma?.independent_numerical_gex_sources??0)],
      ["حالة الخيارات",runtime?.generated_at,
        String(status?.status||"غير متاح")+
        " · سلاسل تنفيذية متحققة: "+String(status?.live_primary_chains??0)],
      ["اختبار النتائج التاريخية",audit?.generated_at,
        auditRecent?
          (applicablePct?
            "تغطية 60 دقيقة: "+applicablePct+" من القابلة للقياس ("+covered+"/"+applicable+")"+
            " · "+coveragePct+" من الكل · غير قابلة للقياس بشموع الجلسة: "+afterClose+" أفقها بعد الإغلاق"+
            (preOpen?" و"+preOpen+" أفقها قبل الافتتاح":""):
            "تغطية 60 دقيقة: "+coveragePct+" ("+covered+"/"+audited+")")+
          " · المعاد فحصها بتوقيت إغلاق الشمعة: "+verifiedV2+
          " · جاهزية الترقية: "+(audit?.promotion_gate?.coverage_ready===true?"شرط التغطية مستوفى فقط":"غير مستوفاة")+
          " · معدل نجاح مثبت: غير متاح"
          :"لا يوجد تقرير تاريخي حديث موثوق؛ لا يمكن استنتاج نجاح التوصيات"],
    ]){
      const card=txt("article","","terminal-trust-card");
      card.append(txt("strong",feed[0]));
      card.append(txt("small","آخر إنشاء للتقرير: "+stamp(feed[1])));
      card.append(txt("p",feed[2]));
      wrap.append(card);
    }
    if(!reportCurrent)return;
    for(const source of sources){
      if(!source||typeof source!=="object")continue;
      const card=txt("article","","terminal-trust-card");
      const name=txt("div","","terminal-trust-head");
      const verified=source.ok===true&&source.content_status &&
        source.transport_reachable===true;
      name.append(txt("strong",String(source.name||"مصدر غير معروف").slice(0,80)),
        chip(verified?"المحتوى صالح للفحص":
          source.transport_reachable?"الاستجابة غير مؤهلة":"تعطل الاتصال",
          verified?"UP":"STALE"));
      card.append(name);
      card.append(txt("small","المصدر: "+String(source.family||"—")+
        " · "+(source.authority==="official"?"رسمي":"بحثي غير رسمي")));
      card.append(txt("p","النتيجة: "+String(source.content_status||source.error||"غير موثق").slice(0,220)));
      if(source.source_observation_date)
        card.append(txt("small","تاريخ البيانات الأصلي: "+String(source.source_observation_date)));
      if(source.status)card.append(txt("small"," · HTTP "+String(source.status)));
      wrap.append(card);
    }
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
  // Deep link from alerts: ?chart=SYMBOL. Unknown symbols fall back to SPX
  // in refreshSymbols, so a link can never inject arbitrary content.
  function symbolFromLink(search){
    try{
      const value=String(new URLSearchParams(search||"").get("chart")||"").toUpperCase();
      return /^[A-Z][A-Z0-9.-]{0,9}$/.test(value)?value:null;
    }catch{return null;}
  }
  function chooseChart(symbol){
    state.symbol=symbol;state.tf="1d";
    const tf=$("terminal-chart-timeframe");if(tf)tf.value="1d";
    choosePanel("chart");
    $("terminal-panel-chart")?.scrollIntoView({block:"start",behavior:"smooth"});
  }
  function renderOps(){
    const api=typeof window!=="undefined"?window.GhaziOps:null;
    const enginesBox=$("terminal-ops-engines"),feedsBox=$("terminal-ops-feeds");
    if(!api||!enginesBox||!feedsBox)return;
    const now=Date.now();
    const engines=api.engineRows(state.live,now);
    const tone={ok:"up",warn:"warn",bad:"down"};
    enginesBox.replaceChildren();
    for(const row of engines){
      const card=txt("article","","terminal-trust-card");
      const head=txt("div","","terminal-trust-head");
      head.append(txt("strong",row.name),txt("span",row.label,"terminal-chip "+tone[row.kind]));
      card.append(head,
        txt("small","آخر نشر: "+stamp(row.generated_at)+
          (row.age===null?"":" · قبل "+row.age+" دقيقة")+
          (row.max===null?"":" · الحد "+row.max+" دقيقة")),
        txt("small","المرشحون في آخر نشر: "+(row.candidates===null?"غير متاح":row.candidates)));
      enginesBox.append(card);
    }
    if(!engines.length)enginesBox.append(txt("p","حالة المحركات غير متاحة حاليًا.","terminal-empty"));
    const stamps={index:state.quotes?.generated_at,charts:state.charts?.generated_at,
      watch:state.watchCharts?.generated_at,brief:state.brief?.generated_at,
      news:state.news?.generated_at,sec:state.sec?.generated_at,
      freeOptions:state.freeOptions?.generated_at,gamma:state.gamma?.generated_at,
      trust:state.trust?.generated_at,live:state.live?.generated_at,
      audit:state.audit?.generated_at,structural:state.structural?.generated_at,
      strength:state.strength?.generated_at,explosion:state.explosion?.source_generated_at,
      classical:state.classical?.source_generated_at};
    feedsBox.replaceChildren();
    for(const row of api.feedRows(stamps,now)){
      const item=txt("div","","terminal-ops-feed");
      item.append(txt("span",row.name),txt("span",row.label,"terminal-chip "+tone[row.kind]),
        txt("small",(row.age===null?"لم يُحمَّل":"قبل "+row.age+" د")+" · الحد "+row.max+" د"));
      feedsBox.append(item);
    }
    const open=api.regularSession(now);
    put("terminal-ops-session",open?
      "الجلسة الأمريكية مفتوحة: التأخر عن الحد يعني أن التحديث لم يصل في وقته.":
      "السوق الأمريكي مغلق الآن؛ تقادم البيانات خارج الجلسة متوقع ولا يعني عطلًا.");
    const sum=api.summary(engines);
    const late=engines.filter(row=>row.kind!=="ok").map(row=>row.name+": "+row.label);
    put("terminal-ops-overview","صحة المحركات: "+sum.ok+"/"+sum.total+" سليمة"+
      (late.length?" · "+late.join(" · "):"")+(open?"":" · السوق مغلق"));
    const line=$("terminal-ops-overview");
    if(line)line.dataset.kind=sum.kind;
  }
  async function refresh(){
    const types=["index","charts","brief","news","sec","freeOptions","watch","gamma","trust","runtime","audit","structural","oos","sourceAgreement","strength","live","explosion","classical","liquidity","stageEval","optionsAnalytics","dataHub","modelLab","tracking"];
    const read=await Promise.allSettled(types.map(loadFeed));
    [state.quotes,state.charts,state.brief,state.news,state.sec,state.freeOptions,
      state.watchCharts,state.gamma,state.trust,state.runtime,state.audit,state.structural,state.oos,state.sourceAgreement,state.strength,state.live,state.explosion,state.classical,state.liquidity,state.stageEval,state.optionsAnalytics,state.dataHub,state.modelLab,state.tracking]=
      read.map(r=>r.status==="fulfilled"?r.value:null);
    put("terminal-data-state",state.quotes?"مؤشرات متاحة للبحث":"بيانات المؤشرات غير متاحة");
    put("terminal-data-time","آخر تحليل: "+stamp(state.quotes?.generated_at)+
      " · تقارير الأسهم: "+stamp(state.brief?.source_generated_at));
    renderOverview();renderIndices();renderStocks("large");renderStocks("small");renderStructuralWatch();renderExplosion();renderClassical();renderNews();renderTrust();renderDataHub();renderOps();renderOptions();renderFreeOptions();renderStrength();
    refreshSymbols();
    if(state.panel==="chart")renderChart();
  }
  if(typeof module!=="undefined"&&module.exports){
    module.exports={uniqueValidBars,ema,rsi,atr,safeOfficial,safeResearch,liquidityView,symbolFromLink,stageQualityLines,gammaView,optionsSummary,hubLines,sortCandidates,modelLabLines};
  }
  if(typeof document==="undefined")return;
  document.querySelectorAll(".terminal-tab").forEach(button=>
    button.addEventListener("click",()=>choosePanel(button.dataset.terminalTab)));
  $("ghazi-terminal")?.addEventListener("click",event=>{
    const nav=event.target.closest("[data-terminal-go]");
    if(nav&&["overview","indices","large","small","news","chart","options","trust","advanced"].includes(nav.dataset.terminalGo)){
      choosePanel(nav.dataset.terminalGo);
      $("terminal-panel-"+nav.dataset.terminalGo)?.scrollIntoView({block:"start",behavior:"smooth"});
    }
  });
  $("ghazi-terminal")?.addEventListener("click",event=>{
    const button=event.target.closest("[data-chart-symbol]");
    if(button)chooseChart(button.dataset.chartSymbol);
  });
  $("terminal-chart-symbol")?.addEventListener("change",event=>{
    state.pendingSymbol=null;
    state.symbol=event.target.value;state.tf="1d";
    $("terminal-chart-timeframe").value="1d";renderChart();
  });
  $("terminal-explosion-sort")?.addEventListener("change",()=>renderExplosion());
  $("terminal-chart-timeframe")?.addEventListener("change",event=>{
    state.tf=event.target.value;renderChart();
  });
  $("ghazi-terminal")?.addEventListener("click",event=>{
    const btn=event.target.closest("[data-terminal-tf]");
    if(!btn||btn.disabled)return;
    state.tf=btn.dataset.terminalTf;
    const select=$("terminal-chart-timeframe");if(select)select.value=state.tf;
    renderChart();
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
    if(!old.hidden){window.ghaziEnsureLegacyData?.();
      old.scrollIntoView({block:"start",behavior:"smooth"});
      // The legacy chart may have initialized while hidden.
      if(typeof radarData!=="undefined"&&typeof renderMarketChart==="function"&&radarData)
        renderMarketChart(radarData);
    }
  });
  const linked=symbolFromLink(window.location.search);
  if(linked){state.pendingSymbol=linked;chooseChart(linked);}
  refresh().finally(()=>{state.pendingSymbol=null;});
  setInterval(refresh,5*60*1000);
})();
