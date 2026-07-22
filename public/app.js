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

const regimeLabel = (value) => ({ risk_on: "إيجابي", risk_off: "سلبي", mixed: "مختلط", pending: "بانتظار أول فحص" }[value] || value || "—");

function renderFreshness(data) {
  const dot = byId("freshness-dot");
  const label = byId("freshness-label");
  const updated = byId("last-updated");
  dot.className = "status-dot";
  if (!data.generated_at) {
    dot.classList.add("stale");
    label.textContent = "بانتظار أول فحص";
    updated.textContent = "سيُحدّث GitHub Actions البيانات تلقائيًا";
    return;
  }
  const timestamp = new Date(data.generated_at);
  const ageMinutes = (Date.now() - timestamp.getTime()) / 60000;
  if (ageMinutes <= 90) {
    dot.classList.add("fresh");
    label.textContent = "البيانات حديثة";
  } else if (ageMinutes <= 360) {
    dot.classList.add("stale");
    label.textContent = "البيانات متأخرة";
  } else {
    dot.classList.add("error");
    label.textContent = "التحديث متوقف أو قديم";
  }
  updated.textContent = `آخر تحديث: ${timestamp.toLocaleString("ar-SA", { dateStyle: "medium", timeStyle: "short" })}`;
}

function optionMini(option) {
  if (!option) return '<div class="option-mini"><p>لم ينجح عقد مناسب في فلاتر السيولة الحالية.</p></div>';
  const type = option.option_type === "call" ? "CALL" : "PUT";
  return `<div class="option-mini">
    <header><strong class="${type === "CALL" ? "call" : "put"}">${type} ${number(option.strike)}</strong><span>${escapeHtml(option.rating || "—")} · ${number(option.score, 1)}/100</span></header>
    <p>الانتهاء: ${escapeHtml(String(option.expiration || "—").slice(0, 10))}</p>
    <p>الدخول ${money(option.entry_price)} · الهدف ${money(option.target_1)} / ${money(option.target_2)} · الوقف ${money(option.stop_price)}</p>
    <p>Vol/OI ${number(option.vol_oi, 2)}x · Delta ${number(option.delta, 2)} · السبريد ${pct(option.spread_pct)}</p>
  </div>`;
}

function renderStocks(filter = "") {
  const grid = byId("stocks-grid");
  const stocks = (radarData?.stocks || []).filter((stock) => String(stock.symbol || "").includes(filter.toUpperCase()));
  if (!stocks.length) {
    grid.innerHTML = '<div class="empty-state">لا توجد أسهم اجتازت الشروط في آخر فحص.</div>';
    return;
  }
  grid.innerHTML = stocks.map((stock, index) => `
    <article class="stock-card ${index === 0 || stock.new_stock_setup ? "top-pick" : ""}">
      <div class="card-top">
        <div><div class="symbol">${escapeHtml(stock.symbol)}</div><div class="price">السعر ${money(stock.price)}</div></div>
        <div class="score-badge"><strong>${number(stock.score, 1)}</strong><span>${escapeHtml(stock.rating || "—")}</span></div>
      </div>
      <div class="levels">
        <div class="level"><span>الدخول</span><strong>${money(stock.entry_low)}–${money(stock.entry_high)}</strong></div>
        <div class="level"><span>الأهداف</span><strong>${money(stock.target_1)} / ${money(stock.target_2)}</strong></div>
        <div class="level"><span>الوقف</span><strong>${money(stock.stop)}</strong></div>
      </div>
      <div class="chips"><span class="chip">RSI ${number(stock.rsi, 1)}</span><span class="chip">RVOL ${number(stock.relative_volume, 2)}x</span>${stock.breakout ? '<span class="chip">اختراق</span>' : ""}${stock.new_stock_setup ? '<span class="chip">فرصة جديدة</span>' : ""}</div>
      <p class="catalyst">${escapeHtml(stock.catalyst || "لا يوجد محفز قوي حديث")}</p>
      <p class="reasons">${escapeHtml(stock.reasons || "—")}</p>
      ${stock.catalyst_url ? `<a class="source-link" href="${escapeHtml(stock.catalyst_url)}" target="_blank" rel="noopener">فتح المصدر الرسمي ↗</a>` : ""}
      ${optionMini(stock.best_option)}
    </article>`).join("");
}

function renderOptions() {
  const body = byId("options-body");
  const options = radarData?.options || [];
  if (!options.length) {
    body.innerHTML = '<tr><td colspan="9">لا توجد عقود اجتازت جميع الفلاتر في آخر فحص.</td></tr>';
    return;
  }
  body.innerHTML = options.map((option) => {
    const type = option.option_type === "call" ? "CALL" : "PUT";
    return `<tr>
      <td><strong>${escapeHtml(option.symbol)} <span class="${type === "CALL" ? "call" : "put"}">${type} ${number(option.strike)}</span></strong><br><small>${escapeHtml(String(option.expiration || "").slice(0, 10))} · ${number(option.dte, 0)} DTE</small></td>
      <td>${number(option.score, 1)}/100 · ${escapeHtml(option.rating || "—")}</td>
      <td>${money(option.entry_price)}</td>
      <td>${money(option.target_1)} / ${money(option.target_2)}</td>
      <td>${money(option.stop_price)}</td>
      <td>${number(option.vol_oi, 2)}x</td>
      <td>${number(option.delta, 2)}</td>
      <td>${pct(option.iv)}</td>
      <td>${escapeHtml(option.source || "—")}<br><small>${escapeHtml(option.freshness_label || "")}</small></td>
    </tr>`;
  }).join("");
}

function renderCatalysts() {
  const list = byId("catalysts-list");
  const catalysts = radarData?.catalysts || [];
  if (!catalysts.length) {
    list.innerHTML = '<div class="empty-state">لم يُعثر على محفزات رسمية مطابقة خلال فترة البحث.</div>';
    return;
  }
  list.innerHTML = catalysts.map((item) => {
    const negative = Number(item.score) < 0;
    return `<article class="catalyst-row ${negative ? "negative" : ""}">
      <div class="catalyst-score ${negative ? "negative" : "positive"}">${Number(item.score) > 0 ? "+" : ""}${number(item.score, 0)}</div>
      <div><h3>${escapeHtml(item.symbol || "—")} · ${escapeHtml(item.category || item.headline || "محفز")}</h3><p>${escapeHtml(item.headline || "")}<br>${escapeHtml(item.source || "")} · ${escapeHtml(item.form || "")} · ${escapeHtml(item.event_date || "")}</p></div>
      ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">المصدر ↗</a>` : ""}
    </article>`;
  }).join("");
}

function renderAlerts() {
  const section = byId("alerts-section");
  const list = byId("alerts-list");
  const alerts = radarData?.alerts || [];
  section.classList.toggle("hidden", !alerts.length);
  list.innerHTML = alerts.map((alert) => `<div class="alert-item">${escapeHtml(alert)}</div>`).join("");
}

function renderStatus() {
  byId("provider-name").textContent = radarData?.options_provider || "—";
  byId("universe-size").textContent = number(radarData?.universe_size, 0);
  const errors = radarData?.errors || {};
  const entries = Object.entries(errors);
  byId("errors-list").innerHTML = entries.length
    ? entries.map(([key, value]) => `<div class="error-line"><strong>${escapeHtml(key)}</strong>: ${escapeHtml(value)}</div>`).join("")
    : '<p>جميع المصادر المطلوبة أكملت الفحص دون أخطاء مسجلة.</p>';
}

function renderAll(data) {
  radarData = data;
  renderFreshness(data);
  byId("market-regime").textContent = regimeLabel(data.market_regime);
  byId("stock-count").textContent = number(data.summary?.stock_candidates, 0);
  byId("option-count").textContent = number(data.summary?.option_candidates, 0);
  byId("catalyst-count").textContent = number(data.summary?.catalyst_events, 0);
  byId("disclaimer").textContent = data.disclaimer || "النتائج بحثية وليست توصية استثمارية.";
  renderStocks(byId("stock-search").value || "");
  renderOptions();
  renderCatalysts();
  renderAlerts();
  renderStatus();
}

async function fetchRadarData() {
  const failures = [];
  for (const url of DATA_URLS) {
    try {
      const separator = url.includes("?") ? "&" : "?";
      const response = await fetch(`${url}${separator}t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      failures.push(`${url}: ${String(error)}`);
    }
  }
  throw new Error(failures.join(" | "));
}

async function loadData() {
  byId("refresh-button").disabled = true;
  try {
    renderAll(await fetchRadarData());
  } catch (error) {
    byId("freshness-dot").className = "status-dot error";
    byId("freshness-label").textContent = "تعذر تحميل البيانات";
    byId("last-updated").textContent = String(error);
  } finally {
    byId("refresh-button").disabled = false;
  }
}

document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab-button").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    byId(`tab-${button.dataset.tab}`).classList.add("active");
  });
});

byId("stock-search").addEventListener("input", (event) => renderStocks(event.target.value));
byId("refresh-button").addEventListener("click", loadData);
loadData();
setInterval(loadData, 5 * 60 * 1000);
