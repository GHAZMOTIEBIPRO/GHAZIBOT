const DATA_URLS = [
  "https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/main/public/data/latest.json",
  "./data/latest.json",
];
let radarData = null;

const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const number = (value, digits = 2) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString("ar-SA", { maximumFractionDigits: digits }) : "—";
};
const money = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `$${parsed.toFixed(2)}` : "—";
};
const pct = (value, digits = 1) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(digits)}%` : "—";
};
const plainPct = (value, digits = 2) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(digits)}%` : "—";
};
const regimeLabel = (value) => ({
  risk_on: "إيجابي", risk_off: "سلبي", mixed: "مختلط", closed: "السوق مغلق",
  pending: "بانتظار أول فحص",
}[value] || value || "—");
const modeLabel = (value) => ({ free_swing: "Swing مجاني", custom: "إعداد مخصص" }[value] || value || "—");
const sideLabel = (value) => String(value || "").toLowerCase() === "put" ? "PUT" : "CALL";
const rejectionLabels = {
  weak_stock_liquidity: "سيولة السهم ضعيفة",
  price_extended: "الحركة امتدت وفاتت منطقة الدخول",
  score_below_minimum: "الدرجة دون الحد الأدنى",
  dilution_conflicts_with_call: "طرح أو تخفيف يتعارض مع CALL",
  adjusted_or_nonstandard_contract: "عقد معدل أو غير قياسي",
  invalid_bid_ask: "عرض وطلب غير صالحين",
  spread_too_wide: "السبريد واسع",
  option_volume_too_low: "حجم العقد منخفض",
  open_interest_too_low: "Open Interest منخفض",
  data_quality_too_low: "جودة البيانات منخفضة",
  last_trade_too_old: "آخر صفقة قديمة",
  direction_delta_dte_or_score_filter: "لم يطابق الاتجاه أو Delta أو DTE أو الدرجة",
};
const rejectionText = (value) => String(value || "").split(",").filter(Boolean)
  .map((item) => rejectionLabels[item] || item).join("، ");

function renderFreshness(data) {
  const dot = byId("freshness-dot");
  const label = byId("freshness-label");
  const updated = byId("last-updated");
  dot.className = "status-dot";
  if (!data.generated_at) {
    dot.classList.add("stale"); label.textContent = "بانتظار أول فحص";
    updated.textContent = "سيُحدّث GitHub Actions البيانات تلقائيًا"; return;
  }
  const timestamp = new Date(data.generated_at);
  const ageMinutes = (Date.now() - timestamp.getTime()) / 60000;
  if (ageMinutes <= 90) { dot.classList.add("fresh"); label.textContent = "البيانات حديثة"; }
  else if (ageMinutes <= 360) { dot.classList.add("stale"); label.textContent = "البيانات متأخرة"; }
  else { dot.classList.add("error"); label.textContent = "التحديث متوقف أو قديم"; }
  updated.textContent = `آخر تحديث: ${timestamp.toLocaleString("ar-SA", { dateStyle: "medium", timeStyle: "short" })}`;
}

function optionMini(option) {
  if (!option) return '<div class="option-mini"><p>لم ينجح عقد مناسب في بوابة الجودة والسيولة الحالية.</p></div>';
  const type = sideLabel(option.option_type);
  return `<div class="option-mini">
    <header><strong class="${type === "CALL" ? "call" : "put"}">${type} ${number(option.strike)}</strong><span>${escapeHtml(option.rating || "—")} · ${number(option.score, 1)}/100</span></header>
    <p>الانتهاء: ${escapeHtml(String(option.expiration || "—").slice(0, 10))}</p>
    <p>الدخول ${money(option.entry_price)} · الهدف ${money(option.target_1)} / ${money(option.target_2)} · الوقف ${money(option.stop_price)}</p>
    <p>R/R ${number(option.reward_risk_1, 2)}x · Vol/OI ${number(option.vol_oi, 2)}x · Delta ${number(option.delta, 2)}</p>
    <p>البيانات: ${escapeHtml(option.data_status || option.freshness_label || "—")}</p>
  </div>`;
}

function renderStocks(filter = "") {
  const grid = byId("stocks-grid");
  const stocks = (radarData?.stocks || []).filter((stock) => String(stock.symbol || "").includes(filter.toUpperCase()));
  if (!stocks.length) { grid.innerHTML = '<div class="empty-state">لا توجد أسهم اجتازت الشروط في آخر فحص.</div>'; return; }
  grid.innerHTML = stocks.map((stock, index) => {
    const side = sideLabel(stock.setup_side);
    return `<article class="stock-card ${index === 0 || stock.new_stock_setup ? "top-pick" : ""}">
      <div class="card-top"><div><div class="symbol">${escapeHtml(stock.symbol)}</div><div class="price">السعر ${money(stock.price)}</div></div><div class="score-badge"><strong>${number(stock.score, 1)}</strong><span>${escapeHtml(stock.rating || "—")}</span></div></div>
      <div class="levels">
        <div class="level"><span>الدخول</span><strong>${money(stock.entry_low)}–${money(stock.entry_high)}</strong></div>
        <div class="level"><span>الأهداف</span><strong>${money(stock.target_1)} / ${money(stock.target_2)}</strong></div>
        <div class="level"><span>الإبطال</span><strong>${money(stock.invalidation ?? stock.stop)}</strong></div>
      </div>
      <div class="chips">
        <span class="chip ${side === "CALL" ? "call" : "put"}">${side}</span>
        <span class="chip">${escapeHtml(stock.setup_status || "watchlist")}</span>
        <span class="chip">${escapeHtml(stock.entry_state || "waiting")}</span>
        <span class="chip">RSI ${number(stock.rsi, 1)}</span>
        <span class="chip">RVOL ${number(stock.relative_volume, 2)}x</span>
        <span class="chip">${escapeHtml(stock.sector_etf || "SPY")} RS ${plainPct((Number(stock.relative_strength_20d) || 0) * 100, 1)}</span>
        ${stock.breakout ? `<span class="chip">${side === "CALL" ? "اختراق" : "كسر دعم"}</span>` : ""}
        ${stock.new_stock_setup ? '<span class="chip">فرصة جديدة</span>' : ""}
      </div>
      <p class="catalyst">${escapeHtml(stock.catalyst || "لا يوجد محفز قوي حديث")}</p>
      <p class="reasons">${escapeHtml(stock.reasons || "—")}</p>
      ${stock.catalyst_url ? `<a class="source-link" href="${escapeHtml(stock.catalyst_url)}" target="_blank" rel="noopener">فتح المصدر الرسمي ↗</a>` : ""}
      ${optionMini(stock.best_option)}
    </article>`;
  }).join("");
}

function renderOptions() {
  const body = byId("options-body");
  const options = radarData?.options || [];
  if (!options.length) { body.innerHTML = '<tr><td colspan="9">لا توجد عقود اجتازت جميع فلاتر الجودة والمخاطر.</td></tr>'; return; }
  body.innerHTML = options.map((option) => {
    const type = sideLabel(option.option_type);
    const age = Number(option.last_trade_age_minutes);
    const ageText = Number.isFinite(age) ? `${number(age, 0)} دقيقة` : "غير متاح";
    return `<tr>
      <td><strong>${escapeHtml(option.symbol)} <span class="${type === "CALL" ? "call" : "put"}">${type} ${number(option.strike)}</span></strong><br><small>${escapeHtml(String(option.expiration || "").slice(0, 10))} · ${number(option.dte, 0)} DTE</small></td>
      <td>${number(option.score, 1)}/100 · ${escapeHtml(option.rating || "—")}</td>
      <td>${money(option.entry_price)}</td>
      <td>${money(option.target_1)} / ${money(option.target_2)}<br><small>السهم ${money(option.underlying_target_1)} / ${money(option.underlying_target_2)}</small></td>
      <td>${money(option.stop_price)}<br><small>إبطال السهم ${money(option.underlying_invalidation)}</small></td>
      <td>${number(option.reward_risk_1, 2)}x / ${number(option.reward_risk_2, 2)}x</td>
      <td>${number(option.vol_oi, 2)}x</td><td>${number(option.delta, 2)}</td>
      <td>${escapeHtml(option.data_status || "—")}<br><small>${escapeHtml(option.source || "—")} · ${ageText}</small></td>
    </tr>`;
  }).join("");
}

function renderCatalysts() {
  const list = byId("catalysts-list");
  const catalysts = radarData?.catalysts || [];
  if (!catalysts.length) { list.innerHTML = '<div class="empty-state">لم يُعثر على محفزات رسمية مطابقة.</div>'; return; }
  list.innerHTML = catalysts.map((item) => {
    const negative = Number(item.score) < 0;
    const value = Number(item.event_value);
    const valueText = Number.isFinite(value) ? ` · القيمة ${money(value)}` : "";
    const confidence = Number(item.confidence);
    const confidenceText = Number.isFinite(confidence) ? ` · الثقة ${pct(confidence, 0)}` : "";
    return `<article class="catalyst-row ${negative ? "negative" : ""}">
      <div class="catalyst-score ${negative ? "negative" : "positive"}">${Number(item.score) > 0 ? "+" : ""}${number(item.score, 0)}</div>
      <div><h3>${escapeHtml(item.symbol || "—")} · ${escapeHtml(item.category || item.headline || "محفز")}</h3>
      <p>${escapeHtml(item.headline || "")}<br>${escapeHtml(item.source || "")} · ${escapeHtml(item.form || "")} · ${escapeHtml(item.event_date || "")}${valueText}${confidenceText}<br><small>${escapeHtml(item.evidence || item.purpose || "")}</small></p></div>
      ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">المصدر ↗</a>` : ""}
    </article>`;
  }).join("");
}

function renderRejected() {
  const body = byId("rejected-body");
  const rows = radarData?.rejected || [];
  if (!rows.length) { body.innerHTML = '<tr><td colspan="6">لا توجد فرص مرفوضة مسجلة.</td></tr>'; return; }
  body.innerHTML = rows.slice(0, 200).map((row) => {
    const isStock = row.kind === "stock";
    const identity = isStock ? escapeHtml(row.symbol || "—") : `${escapeHtml(row.symbol || "—")}<br><small>${escapeHtml(row.contract_symbol || "—")}</small>`;
    const value = isStock ? money(row.price) : `Spread ${pct(row.spread_pct)}<br><small>${money(row.bid)} / ${money(row.ask)}</small>`;
    return `<tr><td>${isStock ? "سهم" : "عقد"}</td><td>${identity}</td><td>${escapeHtml(rejectionText(row.rejection_reason))}</td><td>${number(row.score, 1)} ${escapeHtml(row.rating || "")}</td><td>${value}</td><td>${escapeHtml(row.source || row.catalyst || "—")}</td></tr>`;
  }).join("");
}

function renderCalibration() {
  const calibration = radarData?.calibration || {};
  const performance = radarData?.performance || {};
  byId("calibration-sample").textContent = `${number(calibration.priced_sample, 0)} / ${number(calibration.minimum_sample, 0)}`;
  byId("calibration-decision").textContent = calibration.decision || "بانتظار البيانات";
  byId("average-mfe").textContent = plainPct(performance.average_mfe_pct, 2);
  byId("average-mae").textContent = plainPct(performance.average_mae_pct, 2);
  byId("calibration-warning").textContent = calibration.warning || "";
  const body = byId("calibration-body");
  const bands = calibration.score_bands || [];
  if (!bands.length) { body.innerHTML = '<tr><td colspan="8">لم تتكوّن عينة معايرة بعد.</td></tr>'; return; }
  body.innerHTML = bands.map((band) => `<tr>
    <td>${escapeHtml(band.band)}</td><td>${number(band.signals, 0)}</td><td>${number(band.priced, 0)}</td>
    <td>${pct(band.target_1_rate)}</td><td>${pct(band.target_2_rate)}</td><td>${pct(band.stop_rate)}</td>
    <td>${plainPct(band.average_mfe_pct, 2)}</td><td>${plainPct(band.average_mae_pct, 2)}</td>
  </tr>`).join("");
}

function renderAlerts() {
  const section = byId("alerts-section");
  const alerts = radarData?.alerts || [];
  section.classList.toggle("hidden", !alerts.length);
  byId("alerts-list").innerHTML = alerts.map((alert) => `<div class="alert-item">${escapeHtml(alert)}</div>`).join("");
}

function renderStatus() {
  byId("provider-name").textContent = radarData?.options_provider || "—";
  byId("universe-size").textContent = number(radarData?.universe_size, 0);
  byId("model-version").textContent = radarData?.model_version || "—";
  const sources = radarData?.universe_sources || {};
  byId("universe-sources").textContent = Object.entries(sources).map(([key, value]) => `${key}: ${number(value, 0)}`).join(" · ") || "—";
  const clock = radarData?.market_clock || {};
  byId("session-status").textContent = clock.is_regular_open ? "مفتوحة" : clock.is_session ? "جلسة مغلقة الآن" : "عطلة سوق";
  const entries = Object.entries(radarData?.errors || {});
  byId("errors-list").innerHTML = entries.length
    ? entries.map(([key, value]) => `<div class="error-line"><strong>${escapeHtml(key)}</strong>: ${escapeHtml(value)}</div>`).join("")
    : '<p>جميع المصادر المطلوبة أكملت الفحص دون أخطاء مسجلة.</p>';
}

function renderAll(data) {
  radarData = data; renderFreshness(data);
  byId("market-regime").textContent = regimeLabel(data.market_regime);
  byId("mode-label").textContent = modeLabel(data.mode);
  byId("stock-count").textContent = number(data.summary?.stock_candidates, 0);
  byId("option-count").textContent = number(data.summary?.option_candidates, 0);
  byId("catalyst-count").textContent = number(data.summary?.catalyst_events, 0);
  byId("rejected-count").textContent = number(data.summary?.rejected_opportunities, 0);
  byId("disclaimer").textContent = data.disclaimer || "النتائج بحثية وليست توصية استثمارية.";
  renderStocks(byId("stock-search").value || ""); renderOptions(); renderCatalysts();
  renderRejected(); renderCalibration(); renderAlerts(); renderStatus();
}

async function fetchRadarData() {
  const failures = [];
  for (const url of DATA_URLS) {
    try {
      const separator = url.includes("?") ? "&" : "?";
      const response = await fetch(`${url}${separator}t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) { failures.push(`${url}: ${String(error)}`); }
  }
  throw new Error(failures.join(" | "));
}

async function loadData() {
  byId("refresh-button").disabled = true;
  try { renderAll(await fetchRadarData()); }
  catch (error) {
    byId("freshness-dot").className = "status-dot error";
    byId("freshness-label").textContent = "تعذر تحميل البيانات";
    byId("last-updated").textContent = String(error);
  } finally { byId("refresh-button").disabled = false; }
}

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab-button").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
    button.classList.add("active"); byId(`tab-${button.dataset.tab}`).classList.add("active");
  });
});
byId("stock-search").addEventListener("input", (event) => renderStocks(event.target.value));
byId("refresh-button").addEventListener("click", loadData);
loadData();
setInterval(loadData, 5 * 60 * 1000);
