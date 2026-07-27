/* Phase 6 UI: independent stock/contract radars and visible source validation. */

const phase60RecommendationClass = (decision) => {
  const text = String(decision || "");
  if (text.includes("دخول مشروط") || text.includes("مرشح")) return "confirmed";
  if (text.includes("استبعاد")) return "reject";
  return "watch";
};

const phase60SourcesHtml = (sources) => {
  const rows = Array.isArray(sources) ? sources : [];
  if (!rows.length) return '<span class="source-pill">مصدر واحد فقط</span>';
  return `<span class="source-list-inline">${rows.map((source) => `<span class="source-pill">${escapeHtml(source)}</span>`).join("")}</span>`;
};

const phase60StockRecommendationMap = () => new Map(
  (radarData?.stock_recommendations || []).map((item) => [String(item.symbol || "").toUpperCase(), item])
);

const phase60ContractRecommendationMap = () => new Map(
  (radarData?.contract_recommendations || []).map((item) => [String(item.contract_symbol || ""), item])
);

renderStocks = function phase60RenderStocks(filter = "") {
  const recommendations = phase60StockRecommendationMap();
  const stocks = (radarData?.stocks || []).filter((stock) => String(stock.symbol || "").includes(filter.toUpperCase()));
  byId("stocks-grid").innerHTML = stocks.length ? stocks.map((stock, index) => {
    const side = sideLabel(stock.setup_side);
    const attention = Number(stock.attention_score);
    const directional = Number(stock.directional_interest_score);
    const recommendation = recommendations.get(String(stock.symbol || "").toUpperCase()) || {};
    const decision = recommendation.decision || "مراقبة فقط";
    const confidence = Number(recommendation.confidence);
    const sourceCount = Number(recommendation.source_count || 1);
    const sourceLabel = sourceCount >= 2 ? `تأكيد ${number(sourceCount, 0)} مصادر` : "مصدر واحد";
    return `<article class="stock-card ${index === 0 || stock.new_stock_setup ? "top-pick" : ""}">
      <div class="card-top"><div><div class="symbol">${escapeHtml(stock.symbol)}</div><div class="price">السعر ${money(stock.price)}</div></div><div class="score-badge"><strong>${number(stock.score, 1)}</strong><span>${escapeHtml(stock.rating || "—")}</span></div></div>
      <div class="recommendation-box ${phase60RecommendationClass(decision)}"><strong>${escapeHtml(decision)}</strong><small>ثقة ${Number.isFinite(confidence) ? `${number(confidence, 1)}%` : "—"} · ${escapeHtml(sourceLabel)}</small><div>${phase60SourcesHtml(recommendation.confirmed_sources)}</div></div>
      <div class="levels"><div class="level"><span>دخول السهم</span><strong>${money(stock.entry_low)}–${money(stock.entry_high)}</strong></div><div class="level"><span>أهداف السهم</span><strong>${money(stock.target_1)} / ${money(stock.target_2)}</strong></div><div class="level"><span>إبطال تحليل السهم</span><strong>${money(stock.invalidation ?? stock.stop)}</strong></div></div>
      <div class="chips"><span class="chip ${side === "CALL" ? "call" : "put"}">${side === "CALL" ? "اتجاه صاعد" : "اتجاه هابط"}</span><span class="chip">${escapeHtml(stock.setup_status || "watchlist")}</span><span class="chip">${escapeHtml(stock.entry_state || "waiting")}</span><span class="chip">${escapeHtml(interestTierLabel(stock.interest_tier))}</span>${Number.isFinite(attention) ? `<span class="chip">اهتمام ${number(attention, 1)}/25</span>` : ""}${Number.isFinite(directional) ? `<span class="chip">قوة الاتجاه ${number(directional, 1)}/25</span>` : ""}<span class="chip">RSI ${number(stock.rsi, 1)}</span><span class="chip">RVOL ${number(stock.finviz_relative_volume ?? stock.relative_volume, 2)}x</span><span class="chip">${escapeHtml(stock.sector_etf || "SPY")} RS ${plainPct((Number(stock.relative_strength_20d) || 0) * 100, 1)}</span></div>
      <p class="catalyst">${escapeHtml(stock.catalyst || "لا يوجد محفز قوي حديث")}</p><p class="reasons">${escapeHtml(stock.reasons || "—")}</p>
      ${stockInterestDetails(stock)}
      ${stock.catalyst_url ? `<a class="source-link" href="${escapeHtml(stock.catalyst_url)}" target="_blank" rel="noopener">فتح المصدر الرسمي ↗</a>` : ""}
    </article>`;
  }).join("") : '<div class="empty-state">لا توجد أسهم اجتازت شروط رادار الأسهم في آخر فحص.</div>';
};

optionRow = function phase60OptionRow(option) {
  const recommendations = phase60ContractRecommendationMap();
  const recommendation = recommendations.get(String(option.contract_symbol || "")) || {};
  const decision = recommendation.decision || "مراقبة عقد";
  const confidence = Number(recommendation.confidence);
  const sourceCount = Number(recommendation.source_count || 1);
  const type = sideLabel(option.option_type);
  const age = Number(option.last_trade_age_minutes);
  const ageText = Number.isFinite(age) ? `${number(age, 0)} دقيقة` : "غير متاح";
  const spike = Number(option.volume_spike_ratio);
  const flowClass = option.buying_flow_type === "Aggressive Buying" ? "call" : "";
  return `<tr>
    <td><strong>${number(option.side_rank, 0)}. ${escapeHtml(option.symbol)} <span class="${type === "CALL" ? "call" : "put"}">${type} ${number(option.strike)}</span></strong><br><small>${escapeHtml(String(option.expiration || "").slice(0, 10))} · ${number(option.dte, 0)} DTE</small></td>
    <td><div class="recommendation-box ${phase60RecommendationClass(decision)}"><strong>${escapeHtml(decision)}</strong><small>ثقة ${Number.isFinite(confidence) ? `${number(confidence, 1)}%` : "—"} · ${number(sourceCount, 0)} مصدر</small></div><strong class="${flowClass}">Flow ${number(option.flow_momentum_score, 1)}</strong><br><small>النموذج ${number(option.score, 1)} · ${escapeHtml(option.rating || "—")}</small></td>
    <td>${money(option.entry_price)}<br><small>Last ${money(option.last)} · Ask ${money(option.ask)}</small></td>
    <td>${money(option.target_1)} / ${money(option.target_2)}<br><small>السهم ${money(option.underlying_target_1)} / ${money(option.underlying_target_2)}</small></td>
    <td>${money(option.stop_price)}<br><small>إبطال السهم ${money(option.underlying_invalidation)}</small></td>
    <td>${number(option.reward_risk_1, 2)}x / ${number(option.reward_risk_2, 2)}x</td>
    <td><strong>${ratioText(option.vol_to_oi_ratio ?? option.vol_oi)}</strong><br><small>Spike ${Number.isFinite(spike) ? ratioText(spike) : "غير متاح"} · Vol ${number(option.volume, 0)} / OI ${number(option.open_interest, 0)}</small></td>
    <td>${number(option.delta, 2)}<br><small>${escapeHtml(flowTypeLabel(option.buying_flow_type))} · ${escapeHtml(option.accumulation_tier || "—")}</small></td>
    <td>${phase60SourcesHtml(recommendation.confirmed_sources)}<br><small>${escapeHtml(option.data_status || "—")} · ${escapeHtml(option.source || "—")} · ${ageText}</small></td>
  </tr>`;
};

const phase60SourceStatusLabel = (status) => ({
  active: "يعمل",
  available: "متاح",
  configured_waiting: "مهيأ ولم يُستخدم",
  configured_error: "مهيأ مع خطأ",
  needs_key: "يحتاج مفتاح",
  entitlement_required: "يحتاج صلاحية بيانات",
  premium_connector: "واجهة مدفوعة",
}[status] || status || "—");

const phase60SourceCard = (item) => `<article class="source-card">
  <header><h4>${escapeHtml(item.name)}</h4><span class="source-status ${escapeHtml(item.status)}">${escapeHtml(phase60SourceStatusLabel(item.status))}</span></header>
  <p>${escapeHtml(item.role || "—")}</p>
  <small>${item.official ? "مصدر رسمي" : "مزود بيانات"} · ${escapeHtml(item.freshness || "—")}</small>
  ${item.note ? `<p><small>${escapeHtml(item.note)}</small></p>` : ""}
  ${item.last_error ? `<p class="reasons"><small>${escapeHtml(item.last_error)}</small></p>` : ""}
</article>`;

function phase60RenderSourceNetwork() {
  const network = radarData?.source_network || {};
  const summary = network.summary || {};
  byId("active-stock-sources").textContent = number(summary.active_stock_sources, 0);
  byId("active-option-sources").textContent = number(summary.active_option_sources, 0);
  byId("configured-stock-sources").textContent = number(summary.configured_stock_sources, 0);
  byId("configured-option-sources").textContent = number(summary.configured_option_sources, 0);
  const policy = network.policy || {};
  byId("source-policy").innerHTML = `<strong>سياسة جودة التوصية:</strong> لا تظهر توصية بحثية قوية قبل تأكيد ${number(policy.strong_recommendation_min_independent_sources || 2, 0)} مصدرين مستقلين. لا يتم كشط مواقع البورصات؛ تغطية Cboe وNasdaq وNYSE وMIAX تتم عبر مزود OPRA مرخص. مصدر واحد = مراقبة فقط.`;
  const stockSources = network.stocks || [];
  const optionSources = network.options || [];
  byId("stock-sources-grid").innerHTML = stockSources.length ? stockSources.map(phase60SourceCard).join("") : '<div class="empty-state">لم تُنشر حالة مصادر الأسهم بعد.</div>';
  byId("option-sources-grid").innerHTML = optionSources.length ? optionSources.map(phase60SourceCard).join("") : '<div class="empty-state">لم تُنشر حالة مصادر العقود بعد.</div>';
}

const phase60BaseRenderAll = renderAll;
renderAll = function phase60RenderAll(data) {
  phase60BaseRenderAll(data);
  phase60RenderSourceNetwork();
  byId("stock-recommendation-count").textContent = number(data.summary?.stock_recommendations, 0);
  byId("contract-recommendation-count").textContent = number(data.summary?.contract_recommendations, 0);
};
