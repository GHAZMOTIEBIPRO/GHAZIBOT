/* GHAZI RADAR – independent long-option position risk calculator.
 * No network, stored data, quotes, or trading authority.
 * Inspired by open-source portfolio risk analytics, not copied from them.
 */
"use strict";

function finiteRiskNumber(value, label) {
  const raw = String(value ?? "").trim();
  if (!raw) throw new Error("أدخل " + label);
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) throw new Error(label + " يجب أن يكون رقمًا غير سالب");
  return n;
}

function calculateLongOptionRisk(input) {
  const side = String(input.side || "").toUpperCase();
  if (side !== "CALL" && side !== "PUT") throw new Error("اختر نوع العقد CALL أو PUT");
  const capital = finiteRiskNumber(input.capital, "رأس المال");
  const riskPct = finiteRiskNumber(input.riskPct, "نسبة المخاطرة");
  const spot = finiteRiskNumber(input.spot, "سعر السهم");
  const strike = finiteRiskNumber(input.strike, "سعر التنفيذ");
  const bid = finiteRiskNumber(input.bid, "سعر Bid");
  const ask = finiteRiskNumber(input.ask, "سعر Ask");
  const fee = finiteRiskNumber(input.fee, "عمولة العملية لكل عقد");
  const targetBid = finiteRiskNumber(input.targetBid, "سعر البيع المستهدف للعقد");
  const stopBid = finiteRiskNumber(input.stopBid, "سعر البيع عند الوقف");
  if (!(capital > 0 && spot > 0 && strike > 0 && ask > 0))
    throw new Error("رأس المال والسهم وسعر التنفيذ وAsk يجب أن تكون أكبر من الصفر");
  if (riskPct <= 0 || riskPct > 100) throw new Error("نسبة المخاطرة بين 0 و100 بالمئة");
  if (bid > ask) throw new Error("سعر Bid لا يجوز أن يتجاوز Ask");
  if (fee > 10000) throw new Error("تحقق من العمولة المدخلة");
  if (capital > 1e12 || ask > 1e8 || strike > 1e8 || spot > 1e8)
    throw new Error("القيم المدخلة أكبر من حدود الحاسبة");

  const multiplier = 100;
  const debitPerContract = ask * multiplier + fee;
  const totalRoundtripFee = 2 * fee; // Simplified exit or closing fee.
  const riskBudget = capital * riskPct / 100;
  const count = Math.max(0, Math.min(1000000,
    Math.floor(Math.min(capital, riskBudget) / debitPerContract)));
  const totalDebit = count * debitPerContract;
  const grossMaxLoss = totalDebit; // Entire paid premium plus entry commission can be lost.
  const currentSpreadPct = ask > 0 ? ((ask - bid) / ((ask + bid) / 2)) * 100 : 0;
  const roundTripProfitAtBid = (futureBid) =>
    ((futureBid - ask) * multiplier - totalRoundtripFee) * count;
  const targetProfit = roundTripProfitAtBid(targetBid);
  const stopProfit = roundTripProfitAtBid(stopBid);
  const plannedStopLoss = Math.max(0, -stopProfit);
  const payoffAtExpiryPerContract = (underlying) => {
    const intrinsic = side === "CALL"
      ? Math.max(underlying - strike, 0) : Math.max(strike - underlying, 0);
    return intrinsic * multiplier - ask * multiplier - totalRoundtripFee;
  };
  const breakeven = side === "CALL"
    ? strike + ask + totalRoundtripFee / multiplier
    : strike - ask - totalRoundtripFee / multiplier;
  // Value of a put at zero underlying price is bounded, unlike a long call.
  const maxProfit = side === "PUT"
    ? Math.max(0, strike * multiplier - ask * multiplier - totalRoundtripFee) * count
    : null;
  const ratio = plannedStopLoss > 0 && targetProfit > 0
    ? targetProfit / plannedStopLoss : null;
  const flags = [];
  if (currentSpreadPct > 15) flags.push("السبريد فوق 15%؛ تكلفة الدخول والخروج مرتفعة");
  if (bid === 0) flags.push("Bid يساوي صفرًا؛ القدرة على الخروج غير مؤكدة");
  if (count === 0) flags.push("حجم المخاطرة المحدد لا يكفي لشراء عقد واحد");
  if (plannedStopLoss > riskBudget + 0.00001)
    flags.push("الخسارة المخططة عند الوقف تتجاوز ميزانية المخاطرة");
  if (stopBid >= ask)
    flags.push("سعر الوقف لا يعكس خسارة مقارنةً بسعر الشراء");
  if (targetBid <= ask)
    flags.push("السعر المستهدف للعقد لا يتجاوز تكلفة شرائه قبل العمولات");
  return {
    side, capital, spot, strike, bid, ask, fee, targetBid, stopBid,
    multiplier, count, riskPct, riskBudget, totalDebit,
    maxLoss: grossMaxLoss, debitPerContract, currentSpreadPct,
    targetProfit, stopProfit, plannedStopLoss, ratio,
    breakeven, maxProfit, flags, payoffAtExpiryPerContract,
  };
}

function formatRiskMoney(value) {
  if (value === null || !Number.isFinite(value)) return "—";
  return "$" + value.toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function formatRiskNumber(value, digits = 2) {
  return Number.isFinite(value) ? value.toLocaleString("en-US", {
    minimumFractionDigits: digits, maximumFractionDigits: digits
  }) : "—";
}

function drawOptionExpiryGraph(svg, calc) {
  const xmlns = "http://www.w3.org/2000/svg";
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const add = (tag, attrs, label) => {
    const el = document.createElementNS(xmlns, tag);
    for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
    if (label !== undefined) el.textContent = label;
    svg.appendChild(el);
    return el;
  };
  const start = Math.max(0, Math.min(calc.spot, calc.strike) * 0.72);
  const end = Math.max(calc.spot, calc.strike) * 1.28;
  const W = 680, H = 240, L = 62, R = 14, T = 20, B = 38;
  const bottom = H - B, right = W - R;
  const xy = Array.from({length: 81}, (_, i) => {
    const underlying = start + (end - start) * i / 80;
    return {underlying, profit: calc.payoffAtExpiryPerContract(underlying)};
  });
  const lo = Math.min(0, ...xy.map(p => p.profit));
  const hi = Math.max(0, ...xy.map(p => p.profit));
  const padding = Math.max(1, (hi - lo) * 0.09);
  const ymin = lo - padding, ymax = hi + padding;
  const x = v => L + ((v - start) / (end - start)) * (right - L);
  const y = v => T + ((ymax - v) / (ymax - ymin)) * (bottom - T);
  add("line",{x1:L,x2:right,y1:y(0),y2:y(0),stroke:"#8192a9","stroke-dasharray":"5,5"});
  add("line",{x1:L,x2:L,y1:T,y2:bottom,stroke:"#8192a9"});
  add("text",{x:8,y:y(0)-5,fill:"#b4becd","font-size":12},"$0");
  for (let i = 0; i <= 4; i++) {
    const underlying = start + (end - start) * i/4;
    add("text",{x:x(underlying),y:H-13,fill:"#b4becd","font-size":11,"text-anchor":"middle"},
      formatRiskNumber(underlying, 0));
  }
  const positive = [], negative = [];
  for (let i = 0; i < xy.length - 1; i++) {
    let a = xy[i], b = xy[i+1];
    const segments = a.profit * b.profit < 0
      ? [a, {underlying:a.underlying + (b.underlying-a.underlying) * (-a.profit)/(b.profit-a.profit), profit:0}, b]
      : [a,b];
    for (let k = 0; k < segments.length - 1; k++) {
      const segment = [segments[k], segments[k+1]];
      (segment[0].profit + segment[1].profit >= 0 ? positive : negative)
        .push("M"+x(segment[0].underlying).toFixed(2)+","+y(segment[0].profit).toFixed(2)
          +" L"+x(segment[1].underlying).toFixed(2)+","+y(segment[1].profit).toFixed(2));
    }
  }
  if (negative.length) add("path",{d:negative.join(" "),fill:"none",stroke:"#ef7979","stroke-width":3});
  if (positive.length) add("path",{d:positive.join(" "),fill:"none",stroke:"#49cba4","stroke-width":3});
  if (calc.breakeven >= start && calc.breakeven <= end) {
    add("line",{x1:x(calc.breakeven),x2:x(calc.breakeven),y1:T,y2:bottom,stroke:"#f5c86b","stroke-dasharray":"3,5"});
  }
  add("text",{x:right,y:16,fill:"#b4becd","font-size":12,"text-anchor":"end"},"ربح/خسارة عند الانتهاء لعقد واحد (دولار)");
}

function initGhaziRiskLab() {
  const form = document.getElementById("ghazi-risk-form");
  if (!form) return;
  const get = name => form.elements.namedItem(name)?.value;
  const put = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  const process = () => {
    try {
      const risk = calculateLongOptionRisk({
        side:get("side"), capital:get("capital"), riskPct:get("riskPct"),
        spot:get("spot"), strike:get("strike"), bid:get("bid"), ask:get("ask"),
        fee:get("fee"), targetBid:get("targetBid"), stopBid:get("stopBid")
      });
      put("risk-error", "");
      put("risk-count", String(risk.count));
      put("risk-budget", formatRiskMoney(risk.riskBudget));
      put("risk-spread", formatRiskNumber(risk.currentSpreadPct) + "%");
      put("risk-debit", formatRiskMoney(risk.totalDebit));
      put("risk-maxloss", formatRiskMoney(risk.maxLoss));
      put("risk-breakeven", formatRiskMoney(risk.breakeven));
      put("risk-target", formatRiskMoney(risk.targetProfit));
      put("risk-stop", formatRiskMoney(risk.stopProfit));
      put("risk-rr", risk.ratio !== null ? formatRiskNumber(risk.ratio) + " : 1" : "غير قابل للحساب");
      put("risk-flags", risk.flags.length ? risk.flags.join(" · ") : "لا توجد ملاحظات رقمية على المدخلات؛ هذا ليس تأكيدًا لجودة العقد أو البيانات.");
      put("risk-maxprofit", risk.side === "CALL"
        ? "غير محدود نظريًا عند الانتهاء (CALL)" : formatRiskMoney(risk.maxProfit));
      drawOptionExpiryGraph(document.getElementById("risk-payoff-chart"), risk);
    } catch (error) {
      put("risk-error", String(error.message || error));
      for (const id of ["risk-count","risk-budget","risk-spread","risk-debit",
        "risk-maxloss","risk-breakeven","risk-target","risk-stop","risk-rr",
        "risk-maxprofit","risk-flags"]) put(id, "—");
      const chart = document.getElementById("risk-payoff-chart");
      if (chart) while(chart.firstChild) chart.removeChild(chart.firstChild);
    }
  };
  form.addEventListener("submit", e => {e.preventDefault(); process();});
  form.addEventListener("input", process);
  form.addEventListener("change", process);
  process();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { calculateLongOptionRisk, formatRiskMoney };
}
if (typeof document !== "undefined") initGhaziRiskLab();
