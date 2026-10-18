"use strict";
// Public-only diagnostics. Never turns snapshot timestamps into quote timestamps.
(() => {
  const ENDPOINTS = [
    "https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/data-status.json",
    "./data/data-status.json",
    "https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/main/public/data/data-status.json",
  ];
  const $ = (id) => document.getElementById(id);
  const show = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  const integer = (value) => Number.isSafeInteger(value) && value >= 0
    ? value.toLocaleString("ar-SA") : "—";
  const timestamp = (value) => {
    const t = Date.parse(value || "");
    return Number.isFinite(t) ? t : null;
  };
  const timeRiyadh = (value) => {
    const t = timestamp(value);
    if (t === null) return "غير موثق";
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Riyadh", dateStyle: "medium", timeStyle: "short",
    }).format(new Date(t));
  };
  const flag = (value) => value === true ? "متوفر بحسب التقرير" :
    value === false ? "غير متوفر — بحث فقط" : "غير مؤكد";
  async function loadOne(url) {
    const response = await fetch(url + (url.includes("?") ? "&" : "?") + "check=" + Date.now(),
      { cache: "no-store" });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const payload = await response.json();
    if (!payload || typeof payload !== "object" || !payload.option_provider_readiness ||
        timestamp(payload.generated_at) === null) throw new Error("تقرير غير صالح");
    return { payload, url };
  }
  function clearData() {
    ["ghazi-stock-sources","ghazi-option-sources","ghazi-research-chains",
     "ghazi-approved-contracts","ghazi-chain-providers","ghazi-report-time",
     "ghazi-sec-status"].forEach((id) => show(id, "—"));
    show("ghazi-option-readiness","غير مؤكد");
    show("ghazi-flow-readiness","غير مؤكد");
    ["ghazi-stock-price-families", "ghazi-context-families",
     "ghazi-cross-chains", "ghazi-options-blockers"].forEach((id) => show(id, "—"));
  }
  function render(result) {
    const { payload: data, url } = result;
    const age = (Date.now() - timestamp(data.generated_at)) / 60000;
    const current = age >= -5 && age <= 90;
    const veryOld = age > 360 || age < -5;
    const readiness = data.option_provider_readiness;
    const sources = data.source_status || {};
    const badge = $("ghazi-quality-badge");
    badge.className = "ghazi-quality-badge " + (current ? "ghazi-current" : "ghazi-degraded");
    const words = veryOld ? "تقرير قديم أو ساعة غير متطابقة" :
      current ? "تقرير حديث — لا يعني تسعيرًا لحظيًا" : "تقرير متأخر";
    badge.textContent = words;
    show("ghazi-stock-sources", integer(sources.active_stock_sources));
    show("ghazi-option-sources", integer(sources.active_option_sources));
    show("ghazi-research-chains", integer(readiness.usable_chains));
    show("ghazi-approved-contracts", integer((data.row_counts || {}).options));
    show("ghazi-option-readiness", flag(readiness.production_quote_ready));
    show("ghazi-flow-readiness", flag(readiness.production_flow_ready));
    show("ghazi-chain-providers", Array.isArray(readiness.sources) && readiness.sources.length ?
      readiness.sources.join("، ") : "لا يوجد مصدر مثبت");
    show("ghazi-report-time", timeRiyadh(data.generated_at));
    const coverage = data.coverage_diagnostics || {};
    const named = (items) => Array.isArray(items) ?
      (items.length ? items.join("، ") : "لا يوجد مصدر مؤكد في هذا التقرير") : "لم تُصدر بيانات تفصيلية بعد";
    show("ghazi-stock-price-families", named(coverage.stock_price_source_families_reported));
    show("ghazi-context-families", named(coverage.stock_non_price_context_sources_reported));
    show("ghazi-cross-chains", integer(coverage.option_cross_source_chains_reported));
    const blockersAR = {
      NO_VERIFIED_OPTION_PROVIDER_FAMILY: "لا توجد عائلة بيانات عقود مثبتة",
      YAHOO_RESEARCH_ONLY: "سلاسل Yahoo البحثية غير صالحة للتنفيذ",
      NO_INDEPENDENT_CROSS_SOURCE_CHAIN: "لا يوجد تأكيد مستقل لسلاسل العقود",
      NO_EXECUTION_GRADE_OPTION_QUOTE: "لا يوجد Bid/Ask تنفيذي حديث وموثق",
      NO_VERIFIED_OPTION_TRADE_FLOW: "لا توجد بيانات تدفق عقود تنفيذية مؤكدة",
    };
    show("ghazi-options-blockers", Array.isArray(coverage.blocking_codes) ?
      (coverage.blocking_codes.length ? coverage.blocking_codes.map((x) => blockersAR[x] || x).join("؛ ") : "لا يوجد عائق مسجل")
      : "ستظهر بعد تحديث التقرير التالي");
    const sec = sources.sec_fulltext;
    show("ghazi-sec-status", sec && sec.available === true ? "متاح في آخر فحص" :
      sec && sec.available === false ? "غير متاح؛ تحقق من مسارات الإفصاح البديلة" : "غير مؤكد");
    const reasons = Array.isArray(readiness.reasons) ? readiness.reasons : [];
    const qualityNote = $("ghazi-quality-note");
    if (readiness.production_quote_ready !== true || readiness.production_flow_ready !== true) {
      qualityNote.textContent = "أوبشن بحثي فقط: مصدر العقد أو توقيت السعر أو دليل التدفق لا يستوفي بوابة التنفيذ. " +
        "لا تجعل كثرة السلاسل أو درجة الترتيب بديلًا عن عروض Bid/Ask موثقة وحديثة.";
    } else {
      qualityNote.textContent = "آخر تقرير سجّل استيفاء متطلبات الجودة؛ تحقّق من طابع وقت كل عرض سعر قبل أي قرار.";
    }
    qualityNote.title = reasons.slice(0,2).join(" | ");
    qualityNote.dataset.origin = url.includes("bot-state") ? "runtime" : "published";
  }
  async function update() {
    const btn = $("ghazi-check-quality");
    if (btn) { btn.disabled = true; btn.textContent = "جارٍ التحقق…"; }
    try {
      const results = await Promise.allSettled(ENDPOINTS.map(loadOne));
      const ok = results.filter((r) => r.status === "fulfilled").map((r) => r.value);
      if (!ok.length) throw new Error("لم يصل تقرير صالح");
      // Select newest provider-generated report, not the newest HTTP response.
      ok.sort((a, b) => timestamp(b.payload.generated_at) - timestamp(a.payload.generated_at));
      render(ok[0]);
    } catch (_) {
      clearData();
      const badge = $("ghazi-quality-badge");
      badge.className = "ghazi-quality-badge ghazi-degraded";
      badge.textContent = "تعذر التحقق من جودة البيانات";
      show("ghazi-quality-note", "فشل الوصول لتقرير الجودة؛ لن نعرض المصادر على أنها حية أو مؤهلة للتنفيذ.");
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "تحديث فحص المصادر"; }
    }
  }
  const btn = $("ghazi-check-quality");
  if (btn) btn.addEventListener("click", update);
  update();
  setInterval(update, 5 * 60 * 1000);
})();
