"use strict";
/* GHAZI research scenario engine. Completed OHLC only, no options quote authority. */
(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  if(root)root.GhaziResearch=api;
})(typeof window!=="undefined"?window:null,function(){
  const finite=n=>typeof n==="number"&&Number.isFinite(n);
  const round=n=>finite(n)?Number(n.toFixed(4)):null;
  function clean(input){
    const seen=new Map();
    for(const bar of Array.isArray(input)?input:[]){
      if(!bar||!((typeof bar.time==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(bar.time)
          &&Number.isFinite(Date.parse(bar.time)))||
         (Number.isInteger(bar.time)&&bar.time>1000000000)))continue;
      if(["open","high","low","close"].some(k=>!finite(bar[k])||bar[k]<=0))continue;
      if(bar.low>Math.min(bar.open,bar.close)||bar.high<Math.max(bar.open,bar.close)||
         bar.high<bar.low)continue;
      // Duplicate dates do not represent independent observations.
      if(!seen.has(bar.time))seen.set(bar.time,bar);
    }
    return [...seen.values()].sort((a,b)=>a.time<b.time?-1:a.time>b.time?1:0).slice(-160);
  }
  function emaValue(rows,n){
    if(rows.length<n)return null;
    const k=2/(n+1);
    let value=rows[0].close;
    for(let i=1;i<rows.length;i++)value=rows[i].close*k+value*(1-k);
    return value;
  }
  function rsiValue(rows){
    if(rows.length<15)return null;
    let g=0,l=0;
    for(let i=1;i<=14;i++){
      const d=rows[i].close-rows[i-1].close;
      g+=Math.max(d,0);l+=Math.max(-d,0);
    }
    g/=14;l/=14;
    for(let i=15;i<rows.length;i++){
      const d=rows[i].close-rows[i-1].close;
      g=(g*13+Math.max(d,0))/14;
      l=(l*13+Math.max(-d,0))/14;
    }
    return l===0?(g>0?100:50):100-100/(1+g/l);
  }
  function atrValue(rows){
    if(rows.length<15)return null;
    const tr=i=>Math.max(rows[i].high-rows[i].low,
      Math.abs(rows[i].high-rows[i-1].close),
      Math.abs(rows[i].low-rows[i-1].close));
    let result=0;
    for(let i=1;i<=14;i++)result+=tr(i);
    result/=14;
    for(let i=15;i<rows.length;i++)result=(result*13+tr(i))/14;
    return result;
  }
  function bias(rows){
    if(rows.length<50)return "INSUFFICIENT";
    const fast=emaValue(rows,20),slow=emaValue(rows,50);
    const rsi=rsiValue(rows),price=rows.at(-1).close;
    if(price>fast&&fast>slow&&rsi>=55)return "UP";
    if(price<fast&&fast<slow&&rsi<=45)return "DOWN";
    return "MIXED";
  }
  function analyze(primary,params={}){
    const bars=clean(primary);
    const base={
      status:"INSUFFICIENT",side:"WAIT",source_role:"OHLC_RESEARCH_ONLY",
      options_quote_verified:false,execution_eligible:false,probability:null,
      reason_ar:"لا توجد 50 شمعة مكتملة كافية لبناء سيناريو متعدد المعايير.",
      activation:null,invalidation:null,target1:null,target2:null,
      support:null,resistance:null,atr:null,source_bar:null,hour_bias:"INSUFFICIENT"
    };
    if(bars.length<50)return base;
    const prior=bars.slice(-21,-1),last=bars.at(-1),range=atrValue(bars);
    if(!prior.length||!finite(range)||range<=0)return base;
    const support=Math.min(...prior.map(v=>v.low));
    const resistance=Math.max(...prior.map(v=>v.high));
    if(!finite(support)||!finite(resistance)||support<=0||resistance<=support)return base;
    const currentBias=bias(bars),hours=clean(params.hourBars);
    const hourBias=hours.length>=50?bias(hours):"INSUFFICIENT";
    const historical=params.current_session_confirmed!==true;
    const mismatch=(currentBias==="UP"&&hourBias==="DOWN")||
      (currentBias==="DOWN"&&hourBias==="UP");
    const side=currentBias==="UP"?"CALL":currentBias==="DOWN"?"PUT":"WAIT";
    const activation=side==="CALL"?resistance:side==="PUT"?support:null;
    const invalidation=side==="CALL"?resistance-range:
      side==="PUT"?support+range:null;
    const target1=side==="CALL"?resistance+range:
      side==="PUT"?support-range:null;
    const target2=side==="CALL"?resistance+2*range:
      side==="PUT"?support-2*range:null;
    const validPrices=[activation,invalidation,target1,target2].every(x=>finite(x)&&x>0);
    const usableSide=validPrices?side:"WAIT";
    const status=historical?"HISTORICAL":
      mismatch?"CONFLICT":
      usableSide==="WAIT"?"NO_TRADE":
      usableSide==="CALL"?(last.close>resistance?"BREAKOUT_OBSERVED":"BULL_WATCH"):
      last.close<support?"BREAKDOWN_OBSERVED":"BEAR_WATCH";
    const reason=historical?
      "آخر شموع التقرير ليست مؤكدة كجلسة حالية؛ المستويات تاريخية وليست إشارة الآن.":
      mismatch?"فريم الساعة يعاكس الاتجاه الفني المختار؛ انتظر توافق الأدلة.":
      usableSide==="WAIT"?"لا يوجد توافق كافٍ بين EMA20 وEMA50 وRSI؛ لا تداول.":
      "تفعيل السيناريو يتطلب حركة سعر مؤكدة عند المستوى وحجمًا مناسبًا؛ التحليل لا يثبت إمكانية تنفيذ عقد.";
    return {
      ...base,status,side:historical||mismatch?"WAIT":usableSide,
      historical_side:usableSide,technical_bias:currentBias,hour_bias:hourBias,
      source_bar:last.time,support:round(support),resistance:round(resistance),
      atr:round(range),last_close:round(last.close),
      activation:validPrices?round(activation):null,
      invalidation:validPrices?round(invalidation):null,
      target1:validPrices?round(target1):null,target2:validPrices?round(target2):null,
      breakout_observed:usableSide==="CALL"&&last.close>resistance,
      breakdown_observed:usableSide==="PUT"&&last.close<support,
      reason_ar:reason,ref:"last_completed_20_bar_range_excluding_latest_plus_atr14",
    };
  }
  return {clean,emaValue,rsiValue,atrValue,bias,analyze};
});
