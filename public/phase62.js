/* Phase 6.2 UI: evidence-class tiers, near-miss contract watchlist, and SPX 0DTE readiness. */

const phase62TierClass = (tier) => ({
  A: "tier-a",
  B: "tier-b",
  C: "tier-c",
}[String(tier || "").toUpperCase()] || "tier-c");

const phase62TierLabel = (tier) => ({
  A: "A مكتمل بحثيًا",
  B: "B قيد التأكيد",
  C: "C غير مكتمل",
}[String(tier || "").toUpperCase()] || "C غير مكتمل");

const phase62MissingHtml = (items) => {
  const rows = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!rows.length) return "";
  return `<p class="tier-missing"><strong>ينقصه:</strong> ${rows.map((item) => escapeHtml(item)).join(" · ")}</p>`;
};

const phase62EvidenceHtml = (items) => {
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) return '<span class="source-pill">لا توجد فئات دليل مستقلة</span>';
  const labels = {
    stock_quote: "سعر السهم",
    options_quote: "Quote العقد",
    options_flow: "Flow مستقل",
    official_catalyst: "محفز رسمي",
    news_sentiment: "أخبار/توجه",
    market_context: "سياق سوقي",
    social_attention: "اهتمام اجتماعي",
  };
  return `<span class="source-list-inline">${rows.map((item) => `<span class="source-pill">${escapeHtml(labels[item] || item)}</span>`).join("")}</span>`;
};

renderStocks = function phase62RenderStocks(filter = "") {
  const recommendations = phase60StockRecommendationMap();
  const stocks = (radarData?.stocks || []).filter((stock) => String(stock.symbol || "").includes(filter.toUpperCase()));
  byId("stocks-grid").innerHTML = stocks.length ? stocks.map((stock, index) => {
    const side = sideLabel(stock.setup_side);
    const attention = Number(stock.attention_score);
    const directional = Number(stock.directional_interest_score);
    const recommendation = recommendations.get(String(stock.symbol || "").toUpperCase()) || {};
    const tier = recommendation.opportunity_tier || stock.opportunity_tier || "C";
    const decision = recommendation.decision || "C — مراقبة فقط";
    const confidence = Number(recommendation.confidence);
    const classCount = Number(recommendation.independent_evidence_class_count || 0);
    return `<article class="stock-card ${phase62TierClass(tier)} ${index === 0 || stock.new_stock_setup ? "top-pick" : ""}">
      <div class="card-top"><div><div class="symbol">${escapeHtml(stock.symbol)}</div><div class="price">السعر ${money(stock.price)}</div></div><div class="score-badge"><strong>${number(stock.score, 1)}</strong><span>${escapeHtml(stock.rating || "—")}</span></div></div>
      <div class="tier-banner ${phase62TierClass(tier)}"><strong>${escapeHtml(phase62TierLabel(tier))}</strong><span>${escapeHtml(decision)}</span></div>
      <div class="recommendation-box ${phase60RecommendationClass(decision)}"><small>ثقة النموذج ${Number.isFinite(confidence) ? `${number(confidence, 1)}%` : "—"} · ${number(classCount, 0)} فئات دليل مستقلة</small><div>${phase62EvidenceHtml(recommendation.evidence_classes)}</div>${phase62MissingHtml(recommendation.missing_confirmations)}</div>
      <div class="levels"><div class="level"><span>دخول السهم</span><strong>${money(stock.entry_low)}–${money(stock.entry_high)}</strong></div><div class="level"><span>أهداف السهم</span><strong>${money(stock.target_1)} / ${money(stock.target_2)}</strong></div><div class="level"><span>إبطال تحليل السهم</span><strong>${money(stock.invalidation ?? stock.stop)}</strong></div></div>
      <div class="chips"><span class="chip ${side === "CALL" ? "call" : "put"}">${side === "CALL" ? "اتجاه صاعد" : "اتجاه هابط"}</span><span class="chip">${escapeHtml(stock.setup_status || "watchlist")}</span><span class="chip">${escapeHtml(stock.entry_state || "waiting")}</span><span class="chip">${escapeHtml(interestTierLabel(stock.interest_tier))}</span>${Number.isFinite(attention) ? `<span class="chip">اهتمام ${number(attention, 1)}/25</span>` : ""}${Number.isFinite(directional) ? `<span class="chip">قوة الاتجاه ${number(directional, 1)}/25</span>` : ""}<span class="chip">RSI ${number(stock.rsi, 1)}</span><span class="chip">RVOL ${number(stock.finviz_relative_volume ?? stock.relative_volume, 2)}x</span><span class="chip">${escapeHtml(stock.sector_etf || "SPY")} RS ${plainPct((Number(stock.relative_strength_20d) || 0) * 100, 1)}</span></div>
      <p class="catalyst">${escapeHtml(stock.catalyst || "لا يوجد محفز قوي حديث")}</p><p class="reasons">${escapeHtml(stock.reasons || "—")}</p>
      ${stockInterestDetails(stock)}
      ${stock.catalyst_url ? `<a class="source-link" href="${escapeHtml(stock.catalyst_url)}" target="_blank" rel="noopener">فتح المصدر الرسمي ↗</a>` : ""}
    </article>`;
  }).join("") : '<div class="empty-state">لا توجد أسهم في آخر فحص.</div>';
};

optionRow = function phase62OptionRow(option) {
  const recommendations = phase60ContractRecommendationMap();
  const key = String(option.contract_symbol || "").replaceAll("O:", "").replaceAll(" ", "");
  const recommendation = recommendations.get(String(option.contract_symbol || ""))
    || recommendations.get(key)
    || (radarData?.contract_recommendations || []).find((row) => String(row.contract_symbol || "").replaceAll("O:", "").replaceAll(" ", "") === key)
    || option;
  const tier = recommendation.opportunity_tier || option.opportunity_tier || "C";
  const decision = recommendation.decision || option.decision || "C — غير مكتمل";
  const confidence = Number(recommendation.confidence);
  const type = sideLabel(option.option_type);
  const age = Number(option.last_trade_age_minutes);
  const ageText = Number.isFinite(age) ? `${number(age, 0)} دقيقة` : "غير متاح";
  const spike = Number(option.volume_spike_ratio);
  const flowClass = option.buying_flow_type === "Aggressive Buying" ? "call" : "";
  return `<tr class="${phase62TierClass(tier)}">
    <td><span class="tier-table-badge ${phase62TierClass(tier)}">${escapeHtml(tier)}</span> <strong>${escapeHtml(option.symbol || "—")} <span class="${type === "CALL" ? "call" : "put"}">${type} ${number(option.strike)}</span></strong><br><small>${escapeHtml(String(option.expiration || "").slice(0, 10))} · ${number(option.dte, 0)} DTE</small><br><small>${escapeHtml(option.contract_symbol || "")}</small></td>
    <td><strong>${escapeHtml(decision)}</strong><br><small>ثقة ${Number.isFinite(confidence) ? `${number(confidence, 1)}%` : "—"}</small>${phase62MissingHtml(recommendation.missing_confirmations)}<strong class="${flowClass}">Flow ${number(option.flow_momentum_score, 1)}</strong><br><small>النموذج ${number(option.score, 1)} · ${escapeHtml(option.rating || "—")}</small></td>
    <td>${money(option.entry_price)}<br><small>Bid ${money(option.bid)} · Ask ${money(option.ask)} · Last ${money(option.last)}</small></td>
    <td>${money(option.target_1)} / ${money(option.target_2)}<br><small>السهم ${money(option.underlying_target_1)} / ${money(option.underlying_target_2)}</small></td>
    <td>${money(option.stop_price)}<br><small>إبطال السهم ${money(option.underlying_invalidation)}</small></td>
    <td>${number(option.reward_risk_1, 2)}x / ${number(option.reward_risk_2, 2)}x</td>
    <td><strong>${ratioText(option.vol_to_oi_ratio ?? option.vol_oi)}</strong><br><small>Spike ${Number.isFinite(spike) ? ratioText(spike) : "غير متاح"} · Vol ${number(option.volume, 0)} / OI ${number(option.open_interest, 0)}</small></td>
    <td>${number(option.delta, 2)}<br><small>Spread ${pct(option.spread_pct, 1)} · ${escapeHtml(flowTypeLabel(option.buying_flow_type))}</small></td>
    <td>${phase62EvidenceHtml(recommendation.evidence_classes)}<br><small>${escapeHtml(option.source || "—")} · ${ageText}</small></td>
  </tr>`;
};

renderOptions = function phase62RenderOptions() {
  const strong = [
    ...(radarData?.top_calls || []),
    ...(radarData?.top_puts || []),
    ...(radarData?.options || []),
  ];
  const watch = radarData?.contract_watchlist || [];
  const unique = new Map();
  [...strong, ...watch].forEach((row) => {
    const key = String(row.contract_symbol || `${row.symbol}-${row.option_type}-${row.strike}-${row.expiration}`);
    if (!unique.has(key)) unique.set(key, row);
  });
  const rows = [...unique.values()];
  const calls = rows.filter((option) => sideLabel(option.option_type) === "CALL");
  const puts = rows.filter((option) => sideLabel(option.option_type) === "PUT");
  byId("call-count").textContent = number(calls.length, 0);
  byId("put-count").textContent = number(puts.length, 0);
  byId("call-section-count").textContent = `${number(calls.length, 0)} عقد A/B/C`;
  byId("put-section-count").textContent = `${number(puts.length, 0)} عقد A/B/C`;
  byId("call-options-body").innerHTML = calls.length
    ? calls.map(optionRow).join("")
    : '<tr><td colspan="9">لا توجد عقود CALL حتى في قائمة القرب من الشروط؛ راجع حالة المصادر.</td></tr>';
  byId("put-options-body").innerHTML = puts.length
    ? puts.map(optionRow).join("")
    : '<tr><td colspan="9">لا توجد عقود PUT حتى في قائمة القرب من الشروط؛ راجع حالة المصادر.</td></tr>';
};

function phase62RenderTierSummary(data) {
  const tiers = data?.opportunity_tiers || {};
  const stocks = tiers.stocks || {};
  const contracts = tiers.contracts || {};
  byId("stock-tier-a").textContent = number(stocks.A, 0);
  byId("stock-tier-b").textContent = number(stocks.B, 0);
  byId("contract-tier-a").textContent = number(contracts.A, 0);
  byId("contract-tier-b").textContent = number(contracts.B, 0);
  const policy = byId("source-policy");
  if (policy) {
    policy.innerHTML = "<strong>سياسة Phase 6.2:</strong> الاستقلال يقاس بفئة الدليل، لا بعدد أسماء المزودين. سهم A يحتاج Quote سوقي وفئة اتجاهية مستقلة. عقد A يحتاج Quote وFlow مستقلين. X وReddit وFINRA سياق مساند فقط.";
  }
}

function phase62RenderSPX0DTE(data) {
  const state = data?.spx_0dte || {};
  const statusLabels = {
    waiting_for_realtime_feed: "بانتظار مصدر لحظي",
    market_closed: "السوق مغلق",
    waiting_for_snapshot_fields: "البيانات اللحظية ناقصة",
    no_confirmed_breakout: "لا يوجد كسر مؤكد",
    confirmed_research_setup: "إعداد بحثي مكتمل",
    watch_pending_flow_confirmation: "إعداد ينتظر Flow",
    insufficient_execution_quality: "جودة التنفيذ غير كافية",
  };
  byId("spx-engine-status").textContent = statusLabels[state.status] || state.status || "—";
  byId("spx-tier").textContent = phase62TierLabel(state.opportunity_tier || "C");
  byId("spx-signal").textContent = state.signal || "لا توجد إشارة";
  byId("spx-spot").textContent = Number.isFinite(Number(state.spot)) ? number(state.spot, 2) : "—";
  byId("spx-orb").textContent = Number.isFinite(Number(state.orb_high))
    ? `${number(state.orb_low, 2)} — ${number(state.orb_high, 2)}`
    : "—";
  byId("spx-vwap").textContent = Number.isFinite(Number(state.vwap)) ? number(state.vwap, 2) : "—";
  byId("spx-expiry").textContent = state.expires_at ? formatRiyadhTime(state.expires_at) : "—";
  const missing = Array.isArray(state.missing_requirements) ? state.missing_requirements : [];
  byId("spx-missing").innerHTML = missing.length
    ? `<ul>${missing.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : '<p>لا توجد متطلبات ناقصة في اللقطة الحالية.</p>';
  byId("spx-note").textContent = state.note || "محرك SPX 0DTE منفصل عن Swing ولا ينفذ أوامر.";
}

const phase62BaseRenderAll = renderAll;
renderAll = function phase62RenderAll(data) {
  phase62BaseRenderAll(data);
  phase62RenderTierSummary(data);
  phase62RenderSPX0DTE(data);
};
