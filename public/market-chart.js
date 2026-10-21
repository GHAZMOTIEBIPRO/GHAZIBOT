/* Research-only chart overlays. No external network calls or execution authority. */
let ghaziChart = null;
let ghaziChartSeries = null;
let ghaziChartResizeObserver = null;
const ghaziChartOverlayFlags = { plan: true, trend: true, structure: true };

function ghaziFinitePositive(value) {
  if ((typeof value !== "number" && typeof value !== "string") ||
      (typeof value === "string" && !value.trim())) return null;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function ghaziValidClosedBars(bars) {
  if (!Array.isArray(bars) || bars.length < 1 || bars.length > 1500) return [];
  let previousTime = -Infinity;
  for (const bar of bars) {
    if (!bar || typeof bar !== "object") return [];
    const t = typeof bar.time === "number"
      ? bar.time * 1000
      : typeof bar.time === "string" && /^\d{4}-\d{2}-\d{2}$/.test(bar.time)
        ? Date.parse(bar.time + "T00:00:00Z") : NaN;
    if (!Number.isFinite(t) || t <= previousTime) return [];
    previousTime = t;
    const o = ghaziFinitePositive(bar.open);
    const h = ghaziFinitePositive(bar.high);
    const l = ghaziFinitePositive(bar.low);
    const c = ghaziFinitePositive(bar.close);
    if (o === null || h === null || l === null || c === null ||
        h < Math.max(o, c) || l > Math.min(o, c) || l > h) return [];
  }
  return bars;
}

function ghaziChartResearchLevels(bars) {
  const valid = ghaziValidClosedBars(bars);
  if (!valid.length) return null;
  const closes = valid.map(bar => Number(bar.close));
  function ema(period) {
    if (closes.length < period) return null;
    let value = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
    const alpha = 2 / (period + 1);
    for (let i = period; i < closes.length; i++) {
      value = alpha * closes[i] + (1 - alpha) * value;
    }
    return Number(value.toFixed(4));
  }
  // Exclude the current last *closed* candle from the historical trigger window.
  const prior20 = valid.length >= 21 ? valid.slice(-21, -1) : [];
  const resistance = prior20.length === 20
    ? Math.max(...prior20.map(bar => Number(bar.high))) : null;
  const support = prior20.length === 20
    ? Math.min(...prior20.map(bar => Number(bar.low))) : null;
  const lastClose = closes[closes.length - 1];
  return {
    ema20: ema(20), ema50: ema(50),
    resistance20: resistance, support20: support,
    close: lastClose,
    breakout: resistance !== null && lastClose > resistance ? "ABOVE_PRIOR_20_HIGH"
      : support !== null && lastClose < support ? "BELOW_PRIOR_20_LOW"
        : "NONE",
    source: "COMPLETED_BARS_RESEARCH",
    execution_grade: false,
    probability: null,
  };
}

function ghaziDestroyChart() {
  if (ghaziChartResizeObserver) {
    ghaziChartResizeObserver.disconnect();
    ghaziChartResizeObserver = null;
  }
  if (ghaziChart) {
    ghaziChart.remove();
    ghaziChart = null;
    ghaziChartSeries = null;
  }
}

function ghaziChartLibraryReady() {
  return typeof LightweightCharts !== "undefined" &&
    typeof LightweightCharts.createChart === "function";
}

function ghaziCreateSeries(chart) {
  if (typeof chart.addSeries === "function" && LightweightCharts.CandlestickSeries) {
    return chart.addSeries(LightweightCharts.CandlestickSeries, {});
  }
  if (typeof chart.addCandlestickSeries === "function") {
    return chart.addCandlestickSeries({});
  }
  throw new Error("Candlestick API غير متاحة");
}

function ghaziAddPriceLine(series, price, title) {
  const value = ghaziFinitePositive(price);
  if (value === null) return;
  series.createPriceLine({
    price: value, title, axisLabelVisible: true, lineWidth: 1,
  });
}

function ghaziEnsureChartToolbar(container) {
  if (!container || !container.parentNode || typeof document.createElement !== "function") return;
  let toolbar = document.getElementById("ghazi-chart-overlays-toolbar");
  if (toolbar) return;
  toolbar = document.createElement("div");
  toolbar.id = "ghazi-chart-overlays-toolbar";
  toolbar.className = "chips";
  toolbar.setAttribute("role", "group");
  toolbar.setAttribute("aria-label", "إظهار طبقات تحليل الشارت");
  for (const [key, label] of [
    ["plan", "الدخول والأهداف"], ["trend", "EMA 20 / 50"],
    ["structure", "نطاق 20 شمعة"],
  ]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.setAttribute("aria-pressed", String(ghaziChartOverlayFlags[key]));
    button.textContent = label;
    button.addEventListener("click", () => {
      ghaziChartOverlayFlags[key] = !ghaziChartOverlayFlags[key];
      button.setAttribute("aria-pressed", String(ghaziChartOverlayFlags[key]));
      button.textContent = (ghaziChartOverlayFlags[key] ? "✓ " : "○ ") + label;
      if (typeof radarData !== "undefined" && radarData) {
        const select = document.getElementById("market-chart-symbol");
        if (select) ghaziRenderSelectedChart(radarData, select.value);
      }
    });
    button.textContent = "✓ " + label;
    toolbar.appendChild(button);
  }
  container.parentNode.insertBefore(toolbar, container);
}

function ghaziRenderSelectedChart(data, symbol) {
  const container = byId("market-chart");
  const note = byId("market-chart-note");
  const payload = (data?.charts || {})[symbol];
  ghaziDestroyChart();
  if (!container || !note) return;
  container.innerHTML = "";
  ghaziEnsureChartToolbar(container);
  if (!ghaziChartLibraryReady()) {
    note.textContent = "تعذر تحميل مكتبة الشارت. بيانات الرادار نفسها لم تتأثر.";
    return;
  }
  const valid = ghaziValidClosedBars(payload?.bars);
  if (!valid.length) {
    note.textContent = "لا توجد شموع OHLC صالحة ومنشورة لهذا الرمز؛ لن تُرسم مستويات تقديرية.";
    return;
  }
  ghaziChart = LightweightCharts.createChart(container, {
    autoSize: true,
    layout: { attributionLogo: true },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: false },
  });
  ghaziChartSeries = ghaziCreateSeries(ghaziChart);
  ghaziChartSeries.setData(valid);

  if (ghaziChartOverlayFlags.plan) {
    const levels = payload.levels || {};
    ghaziAddPriceLine(ghaziChartSeries, levels.entry_low, "خطة: بداية الدخول");
    ghaziAddPriceLine(ghaziChartSeries, levels.entry_high, "خطة: نهاية الدخول");
    ghaziAddPriceLine(ghaziChartSeries, levels.target_1, "خطة: T1");
    ghaziAddPriceLine(ghaziChartSeries, levels.target_2, "خطة: T2");
    ghaziAddPriceLine(ghaziChartSeries, levels.target_3, "خطة: T3");
    ghaziAddPriceLine(ghaziChartSeries, levels.stop, "خطة: الإبطال");
  }
  const research = ghaziChartResearchLevels(valid);
  if (research && ghaziChartOverlayFlags.trend) {
    ghaziAddPriceLine(ghaziChartSeries, research.ema20, "EMA20 · تاريخي");
    ghaziAddPriceLine(ghaziChartSeries, research.ema50, "EMA50 · تاريخي");
  }
  if (research && ghaziChartOverlayFlags.structure) {
    ghaziAddPriceLine(ghaziChartSeries, research.resistance20, "مقاومة 20 شمعة سابقة");
    ghaziAddPriceLine(ghaziChartSeries, research.support20, "دعم 20 شمعة سابقة");
  }
  ghaziChart.timeScale().fitContent();
  const side = payload.setup_side === "put" ? "PUT"
    : payload.setup_side === "call" ? "CALL" : "اتجاه غير محسوم";
  const pattern = research?.breakout === "ABOVE_PRIOR_20_HIGH" ? " · إغلاق فوق قمة 20 شمعة"
    : research?.breakout === "BELOW_PRIOR_20_LOW" ? " · إغلاق تحت قاع 20 شمعة" : "";
  note.textContent = symbol + " — " + side + pattern +
    " · مشتق من الشموع المنشورة، وليس أسعارًا لحظية أو إثبات تنفيذ. لا يغيّر بوابة V11.";
  if (typeof ResizeObserver !== "undefined") {
    ghaziChartResizeObserver = new ResizeObserver(() => {
      if (ghaziChart) ghaziChart.timeScale().fitContent();
    });
    ghaziChartResizeObserver.observe(container);
  }
}

function renderMarketChart(data) {
  const select = byId("market-chart-symbol");
  const charts = data?.charts || {};
  if (!select) return;
  const symbols = Object.keys(charts);
  const previous = select.value;
  select.innerHTML = symbols.length
    ? symbols.map(symbol => `<option value="${escapeHtml(symbol)}">${escapeHtml(symbol)}</option>`).join("")
    : '<option value="">لا توجد بيانات</option>';
  const selected = symbols.includes(previous) ? previous : (symbols[0] || "");
  select.value = selected;
  ghaziRenderSelectedChart(data, selected);
}

document.addEventListener("DOMContentLoaded", () => {
  const select = byId("market-chart-symbol");
  if (select) {
    select.addEventListener("change", () => {
      if (radarData) ghaziRenderSelectedChart(radarData, select.value);
    });
  }
});
