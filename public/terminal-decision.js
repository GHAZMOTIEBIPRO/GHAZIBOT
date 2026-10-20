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
  return {build,STALE_HOURS};
});
