"use strict";
/* Per-symbol decision summary built only from already-published research
   feeds. It explains a CALL / PUT / WAIT / NO TRADE reading; it never
   creates one, never computes a probability and never hides missing data. */
(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  if(root)root.GhaziDecision=api;
})(typeof window!=="undefined"?window:null,function(){
  const STALE_HOURS=36;
  const num=x=>typeof x==="number"&&Number.isFinite(x);
  const fx=x=>num(x)?x.toLocaleString("en-US",{maximumFractionDigits:2}):"—";
  const ageHours=(stamp,now)=>{
    const t=Date.parse(stamp||"");
    return Number.isFinite(t)&&t<=now+300000?Math.max(0,(now-t)/3600000):null;
  };
  const RULES_AR={
    R1_DAILY_NOT_AGAINST:"اليومي لا يعارض",R2_INTRADAY_ALIGNED:"الساعة و15د متوافقتان",
    R3_ANCHOR_SIDE:"السعر في جهة المرجع (VWAP)",R4_NOT_EXHAUSTED:"لا تشبع في RSI",
    R5_LEVEL_BREAK:"كسر قمة/قاع الجلسة السابقة"};

  function directionFor(symbol,feeds){
    const index=feeds.index?.symbols?.[symbol]?.direction;
    if(index&&index.version){
      const side=index.decision;
      const rules=side==="CALL"||side==="PUT"?index.rules?.[side]||{}:{};
      return {source:"index",decision:side,status:side==="WAIT"?"WAIT":"ACTIONABLE",
        reasons:[index.reason_ar].filter(Boolean),
        passed:Object.entries(rules).filter(([,v])=>v===true).map(([k])=>RULES_AR[k]||k),
        failed:Object.entries(rules).filter(([,v])=>v===false).map(([k])=>RULES_AR[k]||k),
        entry:null,t1:index.targets?.t1??null,t2:index.targets?.t2??null,
        invalidation:index.invalidation??null,rr:null,
        generatedAt:feeds.index.generated_at};
    }
    const row=(feeds.classical?.companies||[]).find(c=>c?.symbol===symbol);
    if(!row)return null;
    const t=row.targets||{};
    const status=row.decision==="WAIT"?"WAIT":
      row.trade_status==="NO_TRADE"||(num(t.t1_reward_to_risk)&&t.t1_reward_to_risk<1)?"NO_TRADE":
      row.trade_status==="ACTIONABLE"?"ACTIONABLE":"UNRATED";
    const tf=row.timeframes||{};
    return {source:"classical",decision:row.decision,status,
      reasons:(row.reasons_ar||[]).slice(0,3),
      passed:[],failed:[],timeframes:tf,
      entry:t.entry??row.confirmation_level??null,t1:t.t1??null,t2:t.t2??null,
      invalidation:row.invalidation_level??null,rr:t.t1_reward_to_risk??null,
      generatedAt:feeds.classical.source_generated_at||feeds.classical.generated_at};
  }

  function build(symbol,feeds,now=Date.now()){
    const dir=directionFor(symbol,feeds);
    const support=[],contra=[],context=[],freshness=[];
    const side=dir?.decision;
    if(dir){
      const age=ageHours(dir.generatedAt,now);
      freshness.push(["الاتجاه",age,age!==null&&age<=STALE_HOURS]);
      for(const p of dir.passed)support.push(p);
      for(const f of dir.failed)contra.push("غير محقق: "+f);
      if(dir.timeframes){
        const v=Object.values(dir.timeframes);
        if(v.length&&v.every(x=>x===v[0]&&x!=="NEUTRAL"))support.push("الأطر الثلاثة متوافقة");
        else if(v.length)contra.push("الأطر الزمنية غير متوافقة");
      }
      if(num(dir.rr)&&dir.rr<1)contra.push("العائد إلى المخاطرة حتى T1 أقل من 1 ("+fx(dir.rr)+")");
    }
    const liq=feeds.liquidity?.symbols?.[symbol];
    if(liq?.status==="OK"){
      const age=ageHours(feeds.liquidity.generated_at,now);
      freshness.push(["الحجم والسيولة",age,age!==null&&age<=STALE_HOURS]);
      const vol=liq.volume;
      if(vol?.state==="HIGH")support.push("حجم أعلى من المعتاد لنفس الوقت (RVOL "+fx(vol.rvol)+")");
      else if(vol?.state==="LOW")contra.push("حجم أقل من المعتاد لنفس الوقت (RVOL "+fx(vol.rvol)+")");
      if(side==="CALL"||side==="PUT"){
        const want=side==="CALL"?"ABOVE":"BELOW";
        if(liq.vwap_position===want)support.push("السعر "+(side==="CALL"?"فوق":"تحت")+" VWAP الجلسة");
        else if(liq.vwap_position&&liq.vwap_position!=="AT")contra.push("السعر "+(side==="CALL"?"تحت":"فوق")+" VWAP الجلسة");
        const b=String(liq.breakout||"");
        if(side==="CALL"&&b==="BREAKOUT_VOLUME_CONFIRMED")support.push("اختراق قمة الأمس بحجم مرتفع");
        if(side==="PUT"&&b==="BREAKDOWN_VOLUME_CONFIRMED")support.push("كسر قاع الأمس بحجم مرتفع");
        if(side==="CALL"&&(b==="FAILED_BREAKOUT"||liq.sweep_proxy==="ABOVE_PRIOR_HIGH_REJECTED"))
          contra.push("رفض فوق قمة الأمس (اختراق فاشل/سحب سيولة محتمل)");
        if(side==="PUT"&&(b==="FAILED_BREAKDOWN"||liq.sweep_proxy==="BELOW_PRIOR_LOW_REJECTED"))
          contra.push("رفض تحت قاع الأمس (كسر فاشل/سحب سيولة محتمل)");
      }
    }
    const news=(feeds.news?.google_news_attention||[]).filter(x=>x?.symbol===symbol);
    const notable=news.filter(x=>x.impact_level==="HIGH"||x.impact_level==="MEDIUM");
    if(notable.length)context.push(notable.length+" خبر بأثر متوسط/مرتفع؛ اتجاه أثره غير مؤكد");
    if(news.some(x=>x.event_topic==="RISK_OR_ADVERSE_EVENT_MENTION"))contra.push("خبر مخاطر أو حدث سلبي مذكور في العناوين");
    if(feeds.news?.generated_at){
      const age=ageHours(feeds.news.generated_at,now);
      freshness.push(["الأخبار",age,age!==null&&age<=STALE_HOURS]);
    }
    const boom=(feeds.explosion?.candidates||[]).find(x=>x?.symbol===symbol);
    if(boom){
      if(boom.stage==="EXTENDED")contra.push("الحركة ممتدة في رادار الانفجار؛ خطر مطاردة");
      else context.push("ضمن رادار الانفجار: "+(boom.stage_ar||boom.stage)+" (أداء المراحل تاريخيًا دون التعادل)");
    }
    const opt=feeds.options?.symbols?.[symbol];
    if(opt?.status==="OK"&&opt.expected_move&&num(opt.expected_move.move_pct)){
      const em=opt.expected_move;
      context.push("حركة متوقعة من عقود Cboe المؤجلة: ±"+fx(em.move_pct)+"% حتى "+em.expiry+
        " ("+fx(em.range_low)+"–"+fx(em.range_high)+")، ليست احتمالًا");
      const age=ageHours(feeds.options.generated_at,now);
      freshness.push(["تحليلات العقود",age,age!==null&&age<=STALE_HOURS]);
      if(num(dir?.t1)&&num(em.range_high)&&num(em.range_low)&&
        (side==="CALL"&&dir.t1>em.range_high||side==="PUT"&&dir.t1<em.range_low))
        contra.push("T1 أبعد من الحركة المتوقعة في سوق العقود حتى "+em.expiry);
    }
    if(symbol==="SPX"&&feeds.gamma?.integrated_engines?.interpretation){
      const g=feeds.gamma.integrated_engines.interpretation;
      context.push("جاما (نموذج): "+(g.hedging_direction_model==="DAMPENING"?"تحوط يهدئ الحركة":
        g.hedging_direction_model==="AMPLIFYING"?"تحوط قد يضخم الحركة":"غير محدد"));
    }
    // Only the direction feed gates the verdict; stale secondary feeds are
    // shown as stale but must not block or create a CALL/PUT.
    const stale=freshness.some(([label,,ok])=>label==="الاتجاه"&&!ok);
    const verdict=!dir?"NO_ANALYSIS":stale?"WAIT_STALE":
      dir.status==="WAIT"?"WAIT":dir.status==="NO_TRADE"?"NO_TRADE":side;
    const VERDICT_AR={CALL:"CALL بحثي",PUT:"PUT بحثي",WAIT:"انتظار",NO_TRADE:"لا تداول",
      WAIT_STALE:"انتظار · بيانات قديمة",NO_ANALYSIS:"لا يوجد تحليل اتجاه لهذا الرمز"};
    const track=feeds.tracking?.symbols?.[symbol];
    const tracking=track?{
      totals:"سجل الرادار لهذا السهم: "+track.totals.signals+" إشارة · بلغت الهدف أولًا "+track.totals.target_first+
        " · ضربت الوقف أولًا "+track.totals.stop_first+" · مفتوحة "+track.totals.pending+" (ليست نسبة نجاح مستقبلية)",
      recent:(track.recent||[]).map(r=>String(r.signal_time||"").slice(0,16).replace("T"," ")+" UTC · "+
        String(r.stage||"—")+" · دخول "+fx(r.entry_price)+" · هدف +"+fx(r.target_pct)+"% / وقف −"+fx(r.stop_pct)+
        "% · "+String(r.status_ar||r.status))
    }:null;
    return {
      symbol,verdict,verdictAr:VERDICT_AR[verdict]||"انتظار",tracking,
      why:dir?dir.reasons:[],support,contra,context,
      levels:dir?{entry:dir.entry,t1:dir.t1,t2:dir.t2,invalidation:dir.invalidation,rr:dir.rr}:null,
      freshness:freshness.map(([label,age,ok])=>({label,ageHours:age,fresh:ok})),
      evidenceBalance:support.length+" داعم / "+contra.length+" معارض",
      probability:null,executionAuthority:false
    };
  }
  const STATE_AR={LIVE:"حي",DELAYED:"رسمي مؤجل",HISTORICAL:"تاريخي",RESEARCH_ONLY:"بحثي",
    MODEL_ESTIMATED:"تقديري",STALE:"قديم",SOURCE_UNAVAILABLE:"المصدر لا يستجيب",VALIDATION_FAILED:"فشل التحقق",
    DATA_UNAVAILABLE:"غير منشور",LICENSE_BLOCKED:"محجوب حتى الترخيص"};
  // Datasets behind each brief section, in the order they are reported.
  const BRIEF_FILES=[["الاتجاه للمؤشرات","index_radar.json"],["الاتجاه للأسهم","classical_direction.json"],
    ["الحجم والسيولة","liquidity_map.json"],["تحليلات العقود","options_analytics.json"],
    ["قائمة المحفزات","catalyst_watchlist.json"],["أحداث FDA","fda_events.json"],
    ["إفصاحات SEC","sec_filing_pulse.json"],["الأخبار العامة","free_public_intelligence.json"]];
  const KIND_AR={FDA_APPROVAL:"موافقة FDA",FDA_SUPPLEMENT:"ملحق FDA",FDA_RECALL:"سحب منتج (FDA)",
    DILUTION_RISK:"إصدار/تخفيف محتمل",CHARTER_OR_REVERSE_SPLIT_REVIEW:"تعديل النظام/تقسيم عكسي محتمل",
    LISTING_NOTICE:"إشعار معايير الإدراج",MATERIAL_AGREEMENT:"اتفاقية/عقد جوهري",EARNINGS_RELEASE:"إعلان نتائج",
    INSIDER_FILING:"إفصاح مطلعين",PERIODIC_REPORT:"تقرير دوري",MERGER_OR_ACQUISITION:"اندماج/استحواذ",
    ACTIVIST_STAKE:"حصة نشطة تتجاوز 5%"};
  const day=s=>String(s||"").slice(0,10)||"—";

  /* Sectioned Arabic brief for one symbol. Catalysts, filings and news are
     context: they never create CALL/PUT; only the price-based direction feed
     can, through build(). Every section says what is missing. */
  function brief(symbol,feeds,now=Date.now()){
    const card=build(symbol,feeds,now);
    const hubRows=Object.fromEntries((feeds.dataHub?.datasets||[]).filter(r=>r&&r.file).map(r=>[r.file,r]));
    const hubState=file=>hubRows[file]?.data_state||"DATA_UNAVAILABLE";
    const priceBlocked=["index_radar.json","classical_direction.json"].every(f=>hubState(f)!=="LIVE"&&hubState(f)!=="DELAYED"&&
      hubState(f)!=="RESEARCH_ONLY");
    const entry=(feeds.catalysts?.watchlist||[]).find(e=>e?.symbol===symbol);
    const filings=(Array.isArray(feeds.sec?.filings)?feeds.sec.filings:[])
      .filter(f=>f?.symbol===symbol&&f.original_filing_confirmed===true)
      .sort((a,b)=>String(b.filing_date).localeCompare(String(a.filing_date))).slice(0,6);
    const context=(feeds.brief?.catalysts||[]).filter(c=>c?.symbol===symbol).slice(0,3);
    const news=[...(feeds.news?.gdelt_attention||[]),...(feeds.news?.press_wire_attention||[])]
      .filter(x=>x?.symbol===symbol).slice(0,4);
    const sections=[];
    const add=(key,title,lines,empty)=>sections.push({key,title,lines:lines.length?lines:[empty],empty:!lines.length});

    // 1. Catalysts and news (official first).
    const cat=(entry?.catalysts||[]).map(c=>(KIND_AR[c.kind]||c.kind)+" · "+day(c.date)+(c.label?" · "+String(c.label).slice(0,90):"")+
      " · "+String(c.source||""));
    const ctx=context.map(c=>"سياق غير مؤكد: "+String(c.headline||"").slice(0,110)+" ("+String(c.source||"")+"، "+day(c.published_at)+")");
    const nw=news.map(x=>"خبر: "+String(x.headline||x.title||"").slice(0,110)+" ("+day(x.published_at||x.seendate)+")");
    add("catalysts","المحفزات والأخبار",[...cat,...nw,...ctx],
      "لا توجد محفزات رسمية أو أخبار مرتبطة بهذا الرمز في آخر 30 يومًا ضمن المصادر المسموحة.");
    // 2. Official filings.
    const secState=hubState("sec_filing_pulse.json");
    add("filings","الإفصاحات الرسمية (SEC)",filings.map(f=>String(f.form)+" · "+day(f.filing_date)+" · "+
      String(f.event_type||"")+((f.event_topics||[]).length?" · "+f.event_topics.join("، "):"")),
      secState==="SOURCE_UNAVAILABLE"||secState==="DATA_UNAVAILABLE"?
        "إفصاحات SEC غير متاحة الآن (الوصول يحتاج SEC_USER_AGENT)؛ لا نستنتج غياب إفصاحات.":
        "لا إفصاحات حديثة لهذا الرمز في نافذة الرصد.");
    // 3. Technical reading and direction.
    const dirLines=[];
    if(card.verdict!=="NO_ANALYSIS"){
      dirLines.push("القراءة: "+card.verdictAr);
      for(const w of card.why)dirLines.push(w);
    }
    add("technical","التحليل الفني والاتجاه",dirLines,
      priceBlocked?"لا توجد قراءة اتجاه: مصادر الأسعار المجانية محجوبة بشروطها؛ الشارت التفاعلي معروض عبر TradingView للعرض فقط.":
        "لا يوجد تحليل اتجاه منشور لهذا الرمز.");
    // 4. Volume and liquidity.
    const liq=feeds.liquidity?.symbols?.[symbol];
    add("liquidity","الحجم والسيولة",liq?.status==="OK"?[
      "الحجم: "+(liq.volume?.state||"—")+(num(liq.volume?.rvol)?" · RVOL "+fx(liq.volume.rvol):""),
      "موقع السعر من VWAP: "+(liq.vwap_position||"—"),liq.breakout?"الاختراق: "+liq.breakout:""].filter(Boolean):[],
      "لا بيانات حجم مرخصة لهذا الرمز؛ لا نقدّر السيولة من مصادر محجوبة.");
    // 5. Options and gamma.
    const opt=feeds.options?.symbols?.[symbol];
    add("options","الخيارات والقاما",opt?.status==="OK"?card.context.filter(x=>x.includes("حركة متوقعة")||x.includes("جاما")):[],
      "لا توجد سلسلة عقود مرخصة لهذا الرمز؛ لا نعرض حجم العقود أو Greeks أو GEX، والتقييم التنفيذي معطل.");
    // 6-7. Scenarios, targets and risks, only from published levels.
    const L=card.levels;
    const hasLevels=L&&num(L.t1)&&num(L.invalidation);
    const isPut=card.verdict==="PUT";
    const trigger=num(L?.entry)?" "+fx(L.entry):"";
    add("scenarios","السيناريو الصاعد والهابط",hasLevels?(isPut?[
      "هابط (القراءة الحالية): الثبات تحت مستوى التأكيد"+trigger+" يفتح T1 "+fx(L.t1)+(num(L.t2)?" ثم T2 "+fx(L.t2):""),
      "صاعد (إلغاء): العودة فوق "+fx(L.invalidation)+" تُلغي القراءة"]:[
      "صاعد (القراءة الحالية): الثبات فوق مستوى التأكيد"+trigger+" يفتح T1 "+fx(L.t1)+(num(L.t2)?" ثم T2 "+fx(L.t2):""),
      "هابط (إلغاء): الكسر تحت "+fx(L.invalidation)+" يُلغي القراءة"]):[],
      "لا يمكن رسم سيناريو سعري دون شموع مرخصة. المحفزات أعلاه سياق يحتاج تأكيدًا سعريًا، ولا تحدد الاتجاه وحدها.");
    add("risks","الأهداف والمخاطر",[...(hasLevels?["T1 "+fx(L.t1)+" · الإلغاء "+fx(L.invalidation)+
      (num(L.rr)?" · عائد/مخاطرة نظري "+fx(L.rr):"")]:[]),...card.contra,
      ...(entry?.dilution_risk?["خطر تخفيف ملكية من إفصاح طرح/تسجيل"]:[]),
      ...(entry?.charter_or_reverse_split_review?["تعديل نظام أساسي قد يشمل تقسيمًا عكسيًا"]:[])],
      "لا أهداف منشورة؛ المخاطر غير قابلة للقياس دون بيانات سعرية.");
    // 8. What can and cannot be concluded.
    const can=[],cannot=[];
    if(cat.length)can.push("يوجد حدث رسمي موثق يستحق المراجعة ("+(Number.isFinite(entry?.catalyst_score)?
      "أولوية "+entry.catalyst_score+"/100":(entry?.highest_importance||"—")+" أولوية")+").");
    for(const r of entry?.risk_flags||[])if(!can.includes(r))can.push("مخاطر معلنة: "+r);
    if(filings.length)can.push("توجد إفصاحات SEC حديثة يمكن قراءتها من المصدر الأصلي.");
    if(card.verdict==="CALL"||card.verdict==="PUT")can.push("قراءة اتجاه بحثية من محرك سعري مستقل، ليست أمر تداول.");
    if(card.verdict==="NO_ANALYSIS"||card.verdict==="WAIT_STALE")cannot.push("اتجاه السهم (CALL/PUT): لا يصدر من الأخبار أو المحفزات وحدها.");
    if(!(liq?.status==="OK"))cannot.push("قوة الحجم والسيولة الآن.");
    if(!(opt?.status==="OK"))cannot.push("نشاط العقود وGreeks وGEX.");
    if(entry&&entry.sub10_confirmed!==true)cannot.push("نطاق السعر (تحت 10$ أم لا): مرشح يحتاج تحققًا سعريًا.");
    add("can","ما يمكن استنتاجه",can,"لا شيء مؤكد من المصادر المتاحة حاليًا لهذا الرمز.");
    add("cannot","ما لا يمكن تحديده",cannot,"—");
    // 9. What to wait for.
    const wait=[];
    if(priceBlocked)wait.push("مصدر أسعار مرخص يسمح بالتحليل (أو بيانات بحث داخلية) لتأكيد رد فعل السعر.");
    if(secState!=="DELAYED"&&secState!=="LIVE")wait.push("تفعيل SEC لقراءة إفصاحات الشركة الرسمية.");
    if(cat.length)wait.push("تأكيد سعري وحجمي بعد المحفز قبل أي قراءة اتجاه.");
    add("wait","ما الذي ننتظره",wait,"تحديث المصادر في الدورة القادمة.");
    // 10. Data status, source and time.
    add("data","حالة البيانات ومصدرها وتوقيتها",BRIEF_FILES.map(([label,file])=>{
      const r=hubRows[file];
      return label+": "+(STATE_AR[hubState(file)]||hubState(file))+(r?.source?" · "+String(r.source).slice(0,40):"")+
        (r?.generated_at?" · "+String(r.generated_at).slice(0,16).replace("T"," ")+" UTC":"");
    }),"لا يوجد كتالوج بيانات منشور.");
    // 11. Signal history.
    add("history","سجل الإشارات السابقة",card.tracking?[card.tracking.totals,...card.tracking.recent]:[],
      "لا إشارات سابقة مسجلة لهذا الرمز.");
    const headline=card.verdict==="NO_ANALYSIS"?
      (cat.length||filings.length?"لا قراءة اتجاه؛ توجد "+(cat.length+filings.length)+" أحداث رسمية تستحق المتابعة.":
        "لا قراءة اتجاه ولا محفزات رسمية حديثة لهذا الرمز."):
      card.verdictAr+" · "+card.evidenceBalance;
    return {symbol,headline,verdict:card.verdict,sections,probability:null,executionAuthority:false};
  }
  return {build,brief,STALE_HOURS};
});
