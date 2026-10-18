"use strict";
// BLS is official monthly context, NEVER a quote or automatic CALL/PUT.
(() => {
  const urls = [
    "https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/bls_macro.json",
    "./data/bls_macro.json"
  ];
  const $ = id => document.getElementById(id);
  const set = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  const format = (value, unit) =>
    typeof value === "number" && Number.isFinite(value)
      ? value.toLocaleString("ar-SA", {maximumFractionDigits: 2}) + " " + unit
      : "غير متاح";
  const valid = value => value && value.schema === "ghazi_radar.bls_macro.v1" &&
    value.authority === "OFFICIAL_MACRO_CONTEXT_ONLY" &&
    value.source_family === "bls_official" &&
    value.is_realtime === false && value.may_trigger_call_put === false &&
    Number.isFinite(Date.parse(value.generated_at)) &&
    value.indicators && typeof value.indicators === "object";
  async function fetchOne(url) {
    const response = await fetch(url + "?r=" + Date.now(), {cache:"no-store"});
    if (!response.ok) throw new Error("HTTP " + response.status);
    const data = await response.json();
    if (!valid(data)) throw new Error("Invalid provenance or schema");
    return data;
  }
  async function update() {
    set("bls-source-status", "جارٍ فحص البيانات الاقتصادية…");
    const ids = ["bls-cpi", "bls-core", "bls-unemployment", "bls-payroll"];
    try {
      const result = await Promise.allSettled(urls.map(fetchOne));
      const passed = result.filter(item => item.status === "fulfilled").map(item => item.value);
      if (!passed.length) throw new Error("missing official feed");
      passed.sort((a,b) => Date.parse(b.generated_at) - Date.parse(a.generated_at));
      const data = passed[0];
      const ageMs = Date.now() - Date.parse(data.generated_at);
      if (ageMs < -300000 || ageMs > 48 * 3600 * 1000)
        throw new Error("stale or future-generated feed");
      for (const [id, key, unit] of [
        ["bls-cpi", "cpi_yoy_pct", "%"],
        ["bls-core", "core_cpi_yoy_pct", "%"],
        ["bls-unemployment", "unemployment_pct", "%"],
        ["bls-payroll", "payroll_change_thousands", "ألف وظيفة"]
      ]) {
        const item = data.indicators[key] || {};
        set(id, format(item.value, unit));
        const month = item.period;
        set(id + "-period", /^\d{4}-(0[1-9]|1[0-2])$/.test(month || "")
          ? "الشهر المرجعي: " + month : "الشهر المرجعي غير مؤكد");
      }
      set("bls-source-status", "المصدر: BLS الرسمي · آخر سحب: " +
        new Intl.DateTimeFormat("en-GB", {
          timeZone:"Asia/Riyadh", dateStyle:"medium", timeStyle:"short"
        }).format(new Date(data.generated_at)) + " بتوقيت الرياض");
    } catch (_) {
      for (const id of ids) {
        set(id, "غير متاح");
        set(id + "-period", "لا تتوفر نسخة حديثة وموثقة");
      }
      set("bls-source-status", "بيانات اقتصادية غير متاحة حاليًا — لا نعرض أرقامًا قديمة");
    }
  }
  const button = $("bls-macro-refresh");
  if (button) button.addEventListener("click", update);
  update();
})();
