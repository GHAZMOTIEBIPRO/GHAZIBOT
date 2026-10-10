let ghaziChart = null;
let ghaziChartSeries = null;
let ghaziChartResizeObserver = null;

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
  return typeof LightweightCharts !== "undefined" && typeof LightweightCharts.createChart === "function";
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
  const value = Number(price);
  if (!Number.isFinite(value)) return;
  series.createPriceLine({
    price: value,
    title,
    axisLabelVisible: true,
    lineWidth: 1,
  });
}

function ghaziRenderSelectedChart(data, symbol) {
  const container = byId("market-chart");
  const note = byId("market-chart-note");
  const charts = data?.charts || {};
  const payload = charts[symbol];
  ghaziDestroyChart();

  if (!container || !note) return;
  container.innerHTML = "";
  if (!ghaziChartLibraryReady()) {
    note.textContent = "تعذر تحميل مكتبة الشارت. بيانات الرادار نفسها لم تتأثر.";
    return;
  }
  if (!payload || !Array.isArray(payload.bars) || payload.bars.length === 0) {
    note.textContent = "لا توجد شموع منشورة لهذا الرمز في آخر دورة.";
    return;
  }

  ghaziChart = LightweightCharts.createChart(container, {
    autoSize: true,
    layout: { attributionLogo: true },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: false },
  });
  ghaziChartSeries = ghaziCreateSeries(ghaziChart);
  ghaziChartSeries.setData(payload.bars);

  const levels = payload.levels || {};
  ghaziAddPriceLine(ghaziChartSeries, levels.entry_low, "بداية الدخول");
  ghaziAddPriceLine(ghaziChartSeries, levels.entry_high, "نهاية الدخول");
  ghaziAddPriceLine(ghaziChartSeries, levels.target_1, "الهدف 1");
  ghaziAddPriceLine(ghaziChartSeries, levels.target_2, "الهدف 2");
  ghaziAddPriceLine(ghaziChartSeries, levels.stop, "الإبطال / الوقف");

  ghaziChart.timeScale().fitContent();
  note.textContent = `${symbol} — ${payload.setup_side === "put" ? "PUT" : "CALL"} — الشارت سياق بحثي ولا يغيّر بوابة V11.`;

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
    ? symbols.map((symbol) => `<option value="${escapeHtml(symbol)}">${escapeHtml(symbol)}</option>`).join("")
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
