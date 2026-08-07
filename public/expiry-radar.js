/* Expiry identity radar UI: series family is independent from holding-horizon DTE. */

const expiryTabOrder = [
  "zero_dte_daily",
  "weekly_series",
  "next_weekly",
  "standard_monthly",
  "next_monthly",
  "all_expirations",
  "longer_dated",
];

const expiryTabLabels = {
  zero_dte_daily: "0DTE / Daily",
  weekly_series: "Weekly Series",
  next_weekly: "Next Weekly",
  standard_monthly: "Standard Monthly",
  next_monthly: "Next Monthly",
  all_expirations: "All Expirations",
  longer_dated: "Longer-Dated",
};

function expiryValue(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : value;
}

function expiryConfidence(row) {
  const raw = Number(row?.classification_confidence);
  return Number.isFinite(raw) ? `${(raw * 100).toFixed(0)}%` : "—";
}

function expiryRadarContractCard(row) {
  const tier = String(row?.opportunity_tier || "C").toUpperCase();
  const side = String(row?.option_type || "").toUpperCase();
  const missing = Array.isArray(row?.missing_confirmations) ? row.missing_confirmations : [];
  const reasons = Array.isArray(row?.reasons) ? row.reasons : [];
  const flowSources = Array.isArray(row?.flow_sources) ? row.flow_sources : [];
  const occ = row?.occ_official_context || {};
  const response = row?.option_expected_response || {};
  const sourceBadge = row?.primary_or_licensed_quote ? "Quote مرخص/أساسي" : "مصدر احتياطي";
  const greekBadge = row?.greeks_source === "MODELED" ? "Greeks MODELED" : `Greeks ${escapeHtml(row?.greeks_source || "Provider")}`;
  const occBadge = occ?.available
    ? `<span class="chip">OCC رسمي ${occ?.aligned_with_contract_side ? "✓" : "سياق"}</span>`
    : "";
  const occDetail = occ?.available
    ? `<p class="catalyst">OCC رسمي (${escapeHtml(occ?.report_key || "—")}): CALL ${number(occ?.call_volume, 0)} · PUT ${number(occ?.put_volume, 0)} · Put/Call ${Number.isFinite(Number(occ?.put_call_ratio)) ? number(occ.put_call_ratio, 2) : "—"}. بيانات مجمعة وليست Quote أو Flow لحظيًا.</p>`
    : "";
  const responseText = response?.available
    ? `${money(response?.option_at_t1)} / ${money(response?.option_at_t2)} / ${money(response?.option_at_t3)}`
    : "محجوب — Greeks/Underlying غير كافية";
  const invalidationText = response?.available ? money(response?.option_at_invalidation) : "—";

  return `<article class="stock-card ${phase62TierClass(tier)}">
    <div class="card-top">
      <div>
        <div class="symbol">${escapeHtml(row?.symbol || "—")} <span class="${side === "CALL" ? "call" : "put"}">${escapeHtml(side || "—")}</span></div>
        <div class="price">${escapeHtml(row?.contract_symbol || "—")}</div>
      </div>
      <div class="score-badge"><strong>${number(row?.rank_score, 1)}</strong><span>${escapeHtml(phase62TierLabel(tier))}</span></div>
    </div>
    <div class="tier-banner ${phase62TierClass(tier)}">
      <strong>${escapeHtml(row?.expiry_family || "UNKNOWN")}</strong>
      <span>${escapeHtml(row?.dte_bucket || "—")} · ${escapeHtml(row?.decision || "مراقبة فقط")}</span>
    </div>
    <div class="chips">
      <span class="chip">${number(row?.dte, 0)} DTE</span>
      <span class="chip">${escapeHtml(String(row?.expiration_date || row?.expiration || "").slice(0, 10))}</span>
      <span class="chip">${escapeHtml(sourceBadge)}</span>
      <span class="chip">${greekBadge}</span>
      <span class="chip">Class ${escapeHtml(expiryConfidence(row))}</span>
      <span class="chip">${escapeHtml(row?.classification_method || "unknown")}</span>
      ${occBadge}
      <span class="chip">Delta ${number(row?.delta, 2)}</span>
      <span class="chip">Spread ${pct(row?.spread_pct, 1)}</span>
      <span class="chip">Vol/OI ${number(row?.vol_to_oi_ratio, 2)}x</span>
    </div>
    <div class="levels">
      <div class="level"><span>سعر العقد / Mid</span><strong>${money(row?.entry_price)}</strong></div>
      <div class="level"><span>استجابة العقد عند T1/T2/T3</span><strong>${responseText}</strong></div>
      <div class="level"><span>استجابة عند إبطال السيناريو</span><strong>${invalidationText}</strong></div>
    </div>
    <p class="reasons">Underlying ${money(row?.underlying_price)} · Moneyness ${Number.isFinite(Number(row?.moneyness_pct)) ? pct(row.moneyness_pct, 1) : "—"} · ${escapeHtml(row?.liquidity_profile || "—")} · ${escapeHtml(row?.settlement_type || "—")} / ${escapeHtml(row?.settlement_time || "—")}</p>
    <p class="reasons">Vol ${number(row?.volume, 0)} · OI ${number(row?.open_interest, 0)} · آخر صفقة ${Number.isFinite(Number(row?.last_trade_age_minutes)) ? `${number(row.last_trade_age_minutes, 0)} دقيقة` : "غير متاحة"}</p>
    <p class="reasons">${escapeHtml(reasons.join(" · ") || "لا توجد أسباب ترتيب إضافية")}</p>
    ${response?.available ? `<p class="catalyst">ترجمة Underlying → Option: ${escapeHtml(response?.method || "—")}. ${escapeHtml(response?.assumptions || "")}</p>` : `<p class="tier-missing">Premium target ثابت معطّل. ${escapeHtml(response?.reason || "لا توجد Greeks موثوقة كفاية لترجمة أهداف السهم إلى العقد.")}</p>`}
    ${occDetail}
    ${flowSources.length ? `<p class="catalyst">Flow مستقل: ${flowSources.map((item) => escapeHtml(item)).join(" · ")}</p>` : ""}
    ${phase62MissingHtml(missing)}
    <p class="reasons">Quote: ${escapeHtml(row?.source || "—")} · Expiry source: ${escapeHtml(row?.expiry_source || "—")} · التصنيف بحثي وRanking Score ليس احتمال ربح.</p>
  </article>`;
}

function expiryRadarSideBlock(rows, side) {
  const items = Array.isArray(rows) ? rows : [];
  const label = side === "calls" ? "CALL" : "PUT";
  const cssClass = side === "calls" ? "call" : "put";
  return `<div class="option-section ${cssClass}-section">
    <div class="option-section-heading"><h3>${label}</h3><span>${number(items.length, 0)} عقد</span></div>
    <div class="cards-grid">${items.length ? items.map(expiryRadarContractCard).join("") : `<div class="empty-state">لا توجد عقود ${label} قابلة للعرض في هذا التصنيف حاليًا.</div>`}</div>
  </div>`;
}

function expiryRadarTabBlock(key, tab) {
  const data = tab || {};
  const label = data?.label || expiryTabLabels[key] || key;
  return `<section class="expiry-tab-panel" data-expiry-panel="${escapeHtml(key)}">
    <div class="section-heading">
      <div>
        <h2>${escapeHtml(label)}</h2>
        <p>Expiry Family هوية السلسلة، وDTE مجرد أفق زمني. Provider metadata يسبق قواعد المنتج، وCalendar inference يظهر فقط كـfallback مع Confidence معلن.</p>
      </div>
    </div>
    ${expiryRadarSideBlock(data.calls, "calls")}
    ${expiryRadarSideBlock(data.puts, "puts")}
  </section>`;
}

function expiryRadarTabsHtml(tabs) {
  return `<div class="expiry-tabs" role="tablist" aria-label="Expiry radar views">
    ${expiryTabOrder.map((key, index) => {
      const count = Number(tabs?.[key]?.count || 0);
      return `<button type="button" class="expiry-tab-button ${index === 0 ? "active" : ""}" data-expiry-tab="${escapeHtml(key)}" role="tab" aria-selected="${index === 0 ? "true" : "false"}">${escapeHtml(expiryTabLabels[key])}<span>${count}</span></button>`;
    }).join("")}
  </div>`;
}

function bindExpiryTabs(container) {
  const buttons = Array.from(container.querySelectorAll("[data-expiry-tab]"));
  const panels = Array.from(container.querySelectorAll("[data-expiry-panel]"));
  const activate = (key) => {
    buttons.forEach((button) => {
      const active = button.dataset.expiryTab === key;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
    });
    panels.forEach((panel) => {
      panel.hidden = panel.dataset.expiryPanel !== key;
    });
  };
  buttons.forEach((button) => button.addEventListener("click", () => activate(button.dataset.expiryTab)));
  activate(expiryTabOrder[0]);
}

function legacyExpiryTabs(profiles) {
  return {
    zero_dte_daily: { label: "0DTE / Daily", ...(profiles?.daily || {}) },
    weekly_series: { label: "Weekly Series", ...(profiles?.weekly || {}) },
    next_weekly: { label: "Next Weekly", calls: [], puts: [], count: 0 },
    standard_monthly: { label: "Standard Monthly", ...(profiles?.monthly || {}) },
    next_monthly: { label: "Next Monthly", calls: [], puts: [], count: 0 },
    all_expirations: { label: "All Expirations", calls: [], puts: [], count: 0 },
    longer_dated: { label: "Longer-Dated", calls: [], puts: [], count: 0 },
  };
}

function renderExpiryRadar(data) {
  const radar = data?.expiry_radar || {};
  const summary = radar.summary || {};
  const profiles = radar.profiles || {};
  const tabs = radar.tabs && Object.keys(radar.tabs).length ? radar.tabs : legacyExpiryTabs(profiles);
  const upside = Array.isArray(radar.upside_stocks) ? radar.upside_stocks : [];
  const dailyNode = byId("expiry-daily-count");
  const weeklyNode = byId("expiry-weekly-count");
  const monthlyNode = byId("expiry-monthly-count");
  const upsideNode = byId("upside-stock-count");
  if (dailyNode) dailyNode.textContent = number(summary.daily, 0);
  if (weeklyNode) weeklyNode.textContent = number(summary.weekly, 0);
  if (monthlyNode) monthlyNode.textContent = number(summary.monthly, 0);
  if (upsideNode) upsideNode.textContent = number(upside.length, 0);

  const container = byId("expiry-radar-sections");
  if (!container) return;
  if (!radar.generated_at) {
    container.innerHTML = '<div class="empty-state">لم يُنشأ رادار مدد الانتهاء في آخر تشغيل بعد.</div>';
    return;
  }
  container.innerHTML = `${expiryRadarTabsHtml(tabs)}<div class="expiry-tab-panels">${expiryTabOrder.map((key) => expiryRadarTabBlock(key, tabs[key])).join("")}</div>`;
  bindExpiryTabs(container);
}

const expiryRadarBaseRenderAll = renderAll;
renderAll = function expiryRadarRenderAll(data) {
  expiryRadarBaseRenderAll(data);
  renderExpiryRadar(data);
};
