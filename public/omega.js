function omegaText(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function omegaArray(value) {
  return Array.isArray(value) ? value : [];
}

function omegaTierClass(value) {
  const tier = String(value || "C").toUpperCase();
  if (tier === "A+" || tier === "A") return "tier-a";
  if (tier === "B") return "tier-b";
  return tier === "X" ? "omega-tier-x" : "";
}

function omegaDimensionRows(dimensions) {
  const labels = {
    catalyst: "Catalyst",
    participation: "Participation",
    supply_structure: "Supply",
    price_structure: "Price",
    options_structure: "Options",
    risk_penalty: "Risk",
  };
  return Object.entries(dimensions || {}).map(([key, value]) => {
    const numeric = Number(value);
    const width = Number.isFinite(numeric) ? Math.max(0, Math.min(100, numeric)) : 0;
    return `<div class="omega-dimension">
      <span>${escapeHtml(labels[key] || key)}</span>
      <div class="omega-meter"><i style="width:${width}%"></i></div>
      <strong>${number(value, 0)}</strong>
    </div>`;
  }).join("");
}

function omegaTargetText(target) {
  if (!target || !Number.isFinite(Number(target.price))) return "—";
  const tag = target.provenance === "MODELED" ? "MODELED" : "SOURCE";
  return `${money(target.price)} · ${escapeHtml(target.label || "")} · ${tag}`;
}

function omegaOpportunityCard(row) {
  const direction = omegaText(row?.direction);
  const tier = omegaText(row?.opportunity_tier, "C");
  const target = row?.target_map || {};
  const contract = row?.best_contract || null;
  const noTrade = row?.no_trade_state
    ? `<p class="omega-state">${escapeHtml(row.no_trade_state)}</p>`
    : "";
  const contractText = contract
    ? `${escapeHtml(contract.contract_symbol || `${contract.symbol || ""} ${contract.option_type || ""}`)} · ${escapeHtml(row.best_expiry_family || contract.expiry_family || "UNKNOWN")}`
    : "NO CONTRACT";
  const reasons = omegaArray(row?.why).slice(0, 6).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const risks = omegaArray(row?.risks).slice(0, 6).map((item) => `<li>${escapeHtml(item)}</li>`).join("");

  return `<article class="stock-card omega-card ${omegaTierClass(tier)}">
    <div class="card-top">
      <div>
        <div class="symbol">${escapeHtml(row?.symbol || "—")}</div>
        <div class="price">${money(row?.price)} · ${escapeHtml(direction)}</div>
      </div>
      <div class="score-badge"><strong>${number(row?.explosion_rank, 1)}</strong><span>${escapeHtml(tier)}</span></div>
    </div>
    <div class="chips">
      <span class="chip">${escapeHtml(row?.day_decision || "NO TRADE")}</span>
      <span class="chip">${escapeHtml(row?.swing_decision || "WATCH")}</span>
      <span class="chip">${row?.data_fresh ? "Fresh" : "Freshness limited"}</span>
      <span class="chip">${escapeHtml(row?.ranking_score_label || "RANKING ONLY")}</span>
    </div>
    ${omegaDimensionRows(row?.dimensions)}
    <div class="levels">
      <div class="level"><span>Entry</span><strong>${money(target?.entry?.low)}–${money(target?.entry?.high)}</strong></div>
      <div class="level"><span>Invalidation</span><strong>${money(target?.invalidation?.price)}</strong></div>
      <div class="level"><span>T1</span><strong>${omegaTargetText(target?.t1)}</strong></div>
      <div class="level"><span>T2</span><strong>${omegaTargetText(target?.t2)}</strong></div>
      <div class="level"><span>T3</span><strong>${omegaTargetText(target?.t3)}</strong></div>
    </div>
    <p class="catalyst"><strong>Best contract:</strong> ${contractText}</p>
    ${noTrade}
    <div class="omega-explain">
      <div><strong>Why it may move</strong><ul>${reasons || "<li>لا توجد تأكيدات كافية</li>"}</ul></div>
      <div><strong>Risks / failure</strong><ul>${risks || "<li>الاتجاه يحتاج تأكيدًا مستمرًا</li>"}</ul></div>
    </div>
    <p class="reasons">probability_of_profit = null · الترتيب ليس ضمانًا أو احتمال ربح معايرًا.</p>
  </article>`;
}

function omegaCatalystCard(cluster) {
  const confirmations = omegaArray(cluster?.confirmations);
  const move = omegaArray(cluster?.why_it_may_move).slice(0, 4).join(" · ");
  const fail = omegaArray(cluster?.why_it_may_fail).slice(0, 4).join(" · ");
  return `<article class="info-card omega-catalyst-card">
    <div class="card-top">
      <div><div class="symbol">${escapeHtml(cluster?.symbol || "—")}</div><div class="price">${escapeHtml(cluster?.category || "UNCLASSIFIED")}</div></div>
      <div class="score-badge"><strong>${number(cluster?.catalyst_quality, 1)}</strong><span>Quality</span></div>
    </div>
    <div class="chips">
      <span class="chip">${escapeHtml(cluster?.directional_bias || "neutral")}</span>
      <span class="chip">${escapeHtml(cluster?.reaction_state || "UNKNOWN")}</span>
      <span class="chip">Age ${number(cluster?.members?.[0]?.age_days, 0)}d</span>
      <span class="chip">Confirm ${number(cluster?.confirmation_count, 0)}</span>
      <span class="chip">Dilution ${number(cluster?.dilution_risk, 0)}/100</span>
    </div>
    <p class="catalyst">${escapeHtml(cluster?.headline || "—")}</p>
    <p class="reasons"><strong>Primary:</strong> ${escapeHtml(cluster?.primary_source || "—")} · ${confirmations.map(escapeHtml).join(" · ")}</p>
    <p class="reasons"><strong>قد يتحرك:</strong> ${escapeHtml(move || "—")}</p>
    <p class="reasons"><strong>قد يفشل:</strong> ${escapeHtml(fail || "—")}</p>
    ${cluster?.primary_url ? `<a class="source-link" href="${escapeHtml(cluster.primary_url)}" target="_blank" rel="noopener">فتح المصدر ↗</a>` : ""}
  </article>`;
}

function renderOmega(data) {
  const omega = data?.omega || {};
  const health = data?.health || {};
  const intel = omega?.catalyst_intelligence || {};
  const sec = data?.sec_incremental_metrics || {};
  const validation = omega?.validation || {};

  const healthNode = byId("omega-health-status");
  const edgeNode = byId("omega-edge-status");
  const cacheNode = byId("omega-sec-cache");
  const clusterNode = byId("omega-cluster-count");
  if (healthNode) healthNode.textContent = omegaText(health.status, "unknown");
  if (edgeNode) edgeNode.textContent = omegaText(validation.edge_status, "EDGE NOT YET PROVEN");
  if (cacheNode) cacheNode.textContent = number(sec.cache_hits, 0);
  if (clusterNode) clusterNode.textContent = number(intel.event_clusters, 0);

  const day = omegaArray(omega?.omega_day);
  const swing = omegaArray(omega?.omega_swing);
  const upside = omegaArray(omega?.explosion_radar?.upside);
  const downside = omegaArray(omega?.explosion_radar?.downside);
  const clusters = omegaArray(intel?.clusters);

  const renderGrid = (id, rows, empty) => {
    const node = byId(id);
    if (!node) return;
    node.innerHTML = rows.length
      ? rows.slice(0, 12).map(omegaOpportunityCard).join("")
      : `<div class="empty-state">${escapeHtml(empty)}</div>`;
  };

  renderGrid("omega-day-grid", day, "لا توجد DAY setup مكتملة الشروط حاليًا.");
  renderGrid("omega-swing-grid", swing, "لا توجد SWING setup مكتملة الشروط حاليًا.");
  renderGrid("omega-upside-grid", upside, "لا توجد Upside candidates.");
  renderGrid("omega-downside-grid", downside, "لا توجد Downside candidates.");

  const catalystNode = byId("omega-catalyst-grid");
  if (catalystNode) {
    catalystNode.innerHTML = clusters.length
      ? clusters.slice(0, 20).map(omegaCatalystCard).join("")
      : '<div class="empty-state">لا توجد Event Clusters موثقة في آخر تشغيل.</div>';
  }
}

const omegaBaseRenderAll = renderAll;
renderAll = function omegaRenderAll(data) {
  omegaBaseRenderAll(data);
  renderOmega(data);
};
