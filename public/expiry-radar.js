/* Daily, weekly, and monthly option-expiry radar UI. */

const expiryBucketLabels = {
  daily: "العقود اليومية — 0 إلى 2 DTE",
  weekly: "العقود الأسبوعية — 3 إلى 10 DTE",
  monthly: "العقود الشهرية — 11 إلى 45 DTE",
};

function expiryRadarContractCard(row) {
  const tier = String(row?.opportunity_tier || "C").toUpperCase();
  const side = String(row?.option_type || "").toUpperCase();
  const missing = Array.isArray(row?.missing_confirmations) ? row.missing_confirmations : [];
  const reasons = Array.isArray(row?.reasons) ? row.reasons : [];
  const flowSources = Array.isArray(row?.flow_sources) ? row.flow_sources : [];
  const sourceBadge = row?.primary_or_licensed_quote ? "Quote مرخص/أساسي" : "مصدر احتياطي";
  return `<article class="stock-card ${phase62TierClass(tier)}">
    <div class="card-top">
      <div>
        <div class="symbol">${escapeHtml(row?.symbol || "—")} <span class="${side === "CALL" ? "call" : "put"}">${escapeHtml(side || "—")}</span></div>
        <div class="price">${escapeHtml(row?.contract_symbol || "—")}</div>
      </div>
      <div class="score-badge"><strong>${number(row?.rank_score, 1)}</strong><span>${escapeHtml(phase62TierLabel(tier))}</span></div>
    </div>
    <div class="tier-banner ${phase62TierClass(tier)}"><strong>${escapeHtml(row?.expiry_bucket_label || "—")}</strong><span>${escapeHtml(row?.decision || "مراقبة فقط")}</span></div>
    <div class="chips">
      <span class="chip">${number(row?.dte, 0)} DTE</span>
      <span class="chip">${escapeHtml(String(row?.expiration || "").slice(0, 10))}</span>
      <span class="chip">${escapeHtml(sourceBadge)}</span>
      <span class="chip">Delta ${number(row?.delta, 2)}</span>
      <span class="chip">Spread ${pct(row?.spread_pct, 1)}</span>
      <span class="chip">Vol/OI ${number(row?.vol_to_oi_ratio, 2)}x</span>
    </div>
    <div class="levels">
      <div class="level"><span>دخول تقديري</span><strong>${money(row?.entry_price)}</strong></div>
      <div class="level"><span>خطة أهداف</span><strong>${money(row?.target_1)} / ${money(row?.target_2)}</strong></div>
      <div class="level"><span>حد مخاطرة</span><strong>${money(row?.stop_price)}</strong></div>
    </div>
    <p class="reasons">Vol ${number(row?.volume, 0)} · OI ${number(row?.open_interest, 0)} · آخر صفقة ${Number.isFinite(Number(row?.last_trade_age_minutes)) ? `${number(row.last_trade_age_minutes, 0)} دقيقة` : "غير متاحة"}</p>
    <p class="reasons">${escapeHtml(reasons.join(" · ") || "لا توجد أسباب ترتيب إضافية")}</p>
    ${flowSources.length ? `<p class="catalyst">Flow مستقل: ${flowSources.map((item) => escapeHtml(item)).join(" · ")}</p>` : ""}
    ${phase62MissingHtml(missing)}
    <p class="reasons">المصدر: ${escapeHtml(row?.source || "—")} · بحثي فقط ولا يضمن الربح.</p>
  </article>`;
}

function expiryRadarSideBlock(rows, side) {
  const items = Array.isArray(rows) ? rows : [];
  const label = side === "calls" ? "CALL" : "PUT";
  const cssClass = side === "calls" ? "call" : "put";
  return `<div class="option-section ${cssClass}-section">
    <div class="option-section-heading"><h3>${label}</h3><span>${number(items.length, 0)} عقد</span></div>
    <div class="cards-grid">${items.length ? items.map(expiryRadarContractCard).join("") : `<div class="empty-state">لا توجد عقود ${label} تستحق العرض في هذا النطاق حاليًا.</div>`}</div>
  </div>`;
}

function expiryRadarBucketBlock(key, profile) {
  const data = profile || {};
  return `<section class="expiry-bucket-block">
    <div class="section-heading"><div><h2>${escapeHtml(expiryBucketLabels[key] || key)}</h2><p>الترتيب يجمع اتجاه السهم والسيولة والسبريد وDelta وحداثة الصفقة ونوع المصدر. درجة A تحتاج Quote مرخصًا وFlow مستقلًا.</p></div></div>
    ${expiryRadarSideBlock(data.calls, "calls")}
    ${expiryRadarSideBlock(data.puts, "puts")}
  </section>`;
}

function renderExpiryRadar(data) {
  const radar = data?.expiry_radar || {};
  const summary = radar.summary || {};
  const profiles = radar.profiles || {};
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
  container.innerHTML = ["daily", "weekly", "monthly"]
    .map((key) => expiryRadarBucketBlock(key, profiles[key]))
    .join("");
}

const expiryRadarBaseRenderAll = renderAll;
renderAll = function expiryRadarRenderAll(data) {
  expiryRadarBaseRenderAll(data);
  renderExpiryRadar(data);
};
