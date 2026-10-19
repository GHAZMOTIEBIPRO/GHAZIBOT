"use strict";
/* Strict publisher-source agreement view. No synthetic confidence/probability. */
(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  if(root)root.GhaziSourceAgreement=api;
})(typeof window!=="undefined"?window:null,function(){
  function evaluate(report){
    if(!report||report.schema!=="ghazi.source_consensus_status.v1"||
        report.research_only!==true||report.quote_execution_eligible!==false||
        report.massive_market_data_published!==false||
        report.independent_price_comparison!=="NOT_VERIFIED"||
        report.concordance_ratio!==null||
        report.independent_confirmations!==0||
        !Array.isArray(report.source_price_families)||
        !report.source_price_families.every(x=>x==="yahoo")||
        !Number.isInteger(report.source_charts_count)||report.source_charts_count<0||
        report.source_charts_count>1000)return null;
    return {
      title:"اتفاق الأسعار بين المصادر",
      status:"غير مثبت",
      explanation:"الشارتات المرصودة من Yahoo فقط؛ لا يوجد تأكيد مستقل لأسعارها. موصل Massive غير مفعل بسبب حدود الترخيص.",
      families:report.source_price_families.length,
      chartCount:report.source_charts_count,
      permissionsNeeded:true,decisionAuthority:false,
    };
  }
  return {evaluate};
});
