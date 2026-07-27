/* Phase 5.1 UI overlay: loaded after app.js and before its async fetch resolves. */

Object.assign(rejectionLabels, {
  option_volume_below_200: "حجم العقد أقل من 200",
  open_interest_below_100: "Open Interest أقل من 100",
  vol_to_oi_below_1_5: "نسبة Vol/OI أقل من 1.5",
  bid_side_or_neutral_trade: "آخر صفقة أقرب إلى Bid؛ لا يوجد شراء صريح",
  missing_last_trade: "سعر آخر صفقة غير متاح",
  no_confirmed_unusual_volume: "لا توجد قفزة حجم أو High Accumulation مؤكدة",
  volume_spike_below_200pct: "قفزة الحجم أقل من 200%",
  score_or_regime_below_minimum: "الدرجة أو نظام السوق دون الحد المطلوب",
  spread_above_15pct: "السبريد يتجاوز 15%",
  delta_outside_030_060: "Delta خارج 0.30–0.60",
  dte_outside_14_60: "DTE خارج 14–60 يومًا",
});

const flowTypeLabel = (value) => ({
  "Aggressive Buying": "شراء هجومي",
  "Moderate Buying": "شراء متوسط",
  Neutral: "محايد",
}[value] || value || "—");

const ratioText = (value) => Number.isFinite(Number(value))
  ? `${number(value, 2)}x`
  : "غير متاح";

optionMini = function phase51OptionMini(option) {
  if (!option) {
    return '<div class="option-mini"><p>لم ينجح عقد شراء كثيف في بوابة الجودة والتدفق الحالية.</p></div>';
  }
  const type = sideLabel(option.option_type);
  return `<div class="option-mini"><header><strong class="${type === "CALL" ? "call" : "put"}">${type} ${number(option.strike)}</strong><span>Flow ${number(option.flow_momentum_score, 1)}/100 · ${escapeHtml(option.rating || "—")}</span></header>
    <p>${escapeHtml(flowTypeLabel(option.buying_flow_type))} · Vol/OI ${ratioText(option.vol_to_oi_ratio ?? option.vol_oi)} · Spike ${ratioText(option.volume_spike_ratio)}</p>
    <p>الانتهاء: ${escapeHtml(String(option.expiration || "—").slice(0, 10))} · ${number(option.dte, 0)} DTE</p>
    <p>الدخول ${money(option.entry_price)} · الهدف ${money(option.target_1)} / ${money(option.target_2)} · الوقف ${money(option.stop_price)}</p>
    <p>Delta ${number(option.delta, 2)} · Spread ${pct(option.spread_pct, 1)}</p>
    <p>البيانات: ${escapeHtml(option.data_status || option.freshness_label || "—")}</p></div>`;
};

optionRow = function phase51OptionRow(option) {
  const type = sideLabel(option.option_type);
  const age = Number(option.last_trade_age_minutes);
  const ageText = Number.isFinite(age) ? `${number(age, 0)} دقيقة` : "غير متاح";
  const spike = Number(option.volume_spike_ratio);
  const flowClass = option.buying_flow_type === "Aggressive Buying" ? "call" : "";
  return `<tr>
    <td><strong>${number(option.side_rank, 0)}. ${escapeHtml(option.symbol)} <span class="${type === "CALL" ? "call" : "put"}">${type} ${number(option.strike)}</span></strong><br><small>${escapeHtml(String(option.expiration || "").slice(0, 10))} · ${number(option.dte, 0)} DTE</small></td>
    <td><strong class="${flowClass}">Flow ${number(option.flow_momentum_score, 1)}</strong><br><small>النموذج ${number(option.score, 1)} · ${escapeHtml(option.rating || "—")}</small></td>
    <td>${money(option.entry_price)}<br><small>Last ${money(option.last)} · Ask ${money(option.ask)}</small></td>
    <td>${money(option.target_1)} / ${money(option.target_2)}<br><small>السهم ${money(option.underlying_target_1)} / ${money(option.underlying_target_2)}</small></td>
    <td>${money(option.stop_price)}<br><small>إبطال السهم ${money(option.underlying_invalidation)}</small></td>
    <td>${number(option.reward_risk_1, 2)}x / ${number(option.reward_risk_2, 2)}x</td>
    <td><strong>${ratioText(option.vol_to_oi_ratio ?? option.vol_oi)}</strong><br><small>Spike ${Number.isFinite(spike) ? ratioText(spike) : "غير متاح"} · Vol ${number(option.volume, 0)} / OI ${number(option.open_interest, 0)}</small></td>
    <td>${number(option.delta, 2)}<br><small>${escapeHtml(flowTypeLabel(option.buying_flow_type))} · ${escapeHtml(option.accumulation_tier || "—")}</small></td>
    <td>${escapeHtml(option.data_status || "—")}<br><small>${escapeHtml(option.source || "—")} · ${escapeHtml(option.freshness_label || "—")} · ${ageText}</small></td>
  </tr>`;
};

renderOptions = function phase51RenderOptions() {
  const fallback = radarData?.options || [];
  const calls = radarData?.top_calls?.length
    ? radarData.top_calls
    : fallback.filter((option) => sideLabel(option.option_type) === "CALL");
  const puts = radarData?.top_puts?.length
    ? radarData.top_puts
    : fallback.filter((option) => sideLabel(option.option_type) === "PUT");
  byId("call-count").textContent = number(calls.length, 0);
  byId("put-count").textContent = number(puts.length, 0);
  byId("call-section-count").textContent = `${number(calls.length, 0)} عقد شراء كثيف`;
  byId("put-section-count").textContent = `${number(puts.length, 0)} عقد شراء كثيف`;
  byId("call-options-body").innerHTML = calls.length
    ? calls.map(optionRow).join("")
    : '<tr><td colspan="9">لا توجد عقود CALL اجتازت Vol/OI وAsk-side والحجم والجودة.</td></tr>';
  byId("put-options-body").innerHTML = puts.length
    ? puts.map(optionRow).join("")
    : '<tr><td colspan="9">لا توجد عقود PUT اجتازت Vol/OI وAsk-side والحجم والجودة.</td></tr>';
};
