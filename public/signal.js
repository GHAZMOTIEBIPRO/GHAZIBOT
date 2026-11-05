'use strict';
// GHAZI RADAR Ω — one signal page: /options/signal/{signal_id}.
// Candles are built only from stamped two-sided quotes (mid of Bid/Ask), never
// from the stock price and never presented as trades. No data => DATA UNAVAILABLE.
(function () {
  const DATA_URLS = [
    'https://raw.githubusercontent.com/GHAZMOTIEBIPRO/GHAZIBOT/bot-state/runtime/public/data/signal_ledger.json',
    '/data/signal_ledger.json',
  ];
  const POLL_MS = 60000;
  const DEFAULT_COLORS = { up: '#26c6a6', down: '#ef5350', entry: '#3d8bfd', target: '#c86dd7', stop: '#ffb347' };
  const STATE_AR = {
    CREATED: 'أُنشئت', WATCHING: 'تحت المراقبة', ENTRY_ELIGIBLE: 'داخل منطقة الدخول (غير قابل للتنفيذ بعد)',
    PAPER_ACTIVE: 'دخول ورقي مفعّل', TARGET_1: 'تحقق الهدف الأول', TARGET_2: 'تحقق الهدف الثاني',
    TARGET_3: 'تحقق الهدف الثالث', STOPPED: 'ضُرب وقف الخسارة', INVALIDATED: 'أُلغيت الفرضية',
    EXPIRED: 'انتهت الصلاحية', DATA_STALE: 'البيانات متوقفة — لا وقف ولا هدف',
    AMBIGUOUS: 'غامضة (الهدف والوقف في الشمعة نفسها)', CLOSED: 'أُغلقت المتابعة',
  };
  const GRADE_AR = { LIVE: 'مباشرة وقابلة للتنفيذ', DELAYED: 'متأخرة — بحث فقط', RESEARCH_ONLY: 'بحثية',
    STALE: 'قديمة', UNAVAILABLE: 'غير متاحة' };
  const GOOD = new Set(['TARGET_1', 'TARGET_2', 'TARGET_3', 'PAPER_ACTIVE']);
  const BAD = new Set(['STOPPED', 'INVALIDATED']);
  const WARN = new Set(['DATA_STALE', 'AMBIGUOUS', 'EXPIRED']);

  function signalIdFrom(loc) {
    const query = new URLSearchParams(loc.search).get('id');
    const parts = loc.pathname.split('/').filter(Boolean);
    const id = query || (parts[0] === 'options' && parts[1] === 'signal' ? parts[2] : '');
    return /^[0-9a-f]{16}$/.test(id || '') ? id : '';
  }

  // One candle per bucket from the mid of each stamped two-sided quote.
  function buildCandles(series, bucketSeconds) {
    const size = bucketSeconds || 60;
    const buckets = new Map();
    for (const q of Array.isArray(series) ? series : []) {
      const ms = Date.parse(q && q.t);
      const bid = Number(q && q.bid), ask = Number(q && q.ask);
      if (!Number.isFinite(ms) || !(bid > 0) || !(ask >= bid)) continue;
      const mid = (bid + ask) / 2;
      const key = Math.floor(ms / 1000 / size) * size;
      const c = buckets.get(key);
      if (!c) buckets.set(key, { time: key, open: mid, high: mid, low: mid, close: mid, n: 1, first: ms, last: ms });
      else {
        c.high = Math.max(c.high, mid); c.low = Math.min(c.low, mid); c.n += 1;
        if (ms >= c.last) { c.close = mid; c.last = ms; }
        if (ms < c.first) { c.open = mid; c.first = ms; }
      }
    }
    return [...buckets.values()].sort((a, b) => a.time - b.time)
      .map(({ time, open, high, low, close, n }) => ({ time, open, high, low, close, quotes: n }));
  }

  function pricesBlocked(signal) {
    return !signal || (signal.display && signal.display.prices !== 'PERMITTED')
      || !signal.levels || signal.levels.status === 'LICENSE_BLOCKED';
  }

  function nyTime(iso) {
    const ms = Date.parse(iso);
    if (!Number.isFinite(ms)) return '—';
    return new Intl.DateTimeFormat('ar-SA-u-nu-latn', { timeZone: 'America/New_York', dateStyle: 'medium',
      timeStyle: 'short' }).format(new Date(ms));
  }

  const api = { signalIdFrom, buildCandles, pricesBlocked };
  if (typeof module !== 'undefined' && module.exports) { module.exports = api; return; }

  const el = id => document.getElementById(id);
  const money = v => (typeof v === 'number' && Number.isFinite(v)) ? v.toFixed(2) : '—';
  let chart = null, candleSeries = null, lastSignal = null;

  function colors() {
    try {
      const saved = JSON.parse(localStorage.getItem('ghazi.signal.colors') || '{}');
      return Object.assign({}, DEFAULT_COLORS, saved && typeof saved === 'object' ? saved : {});
    } catch (_) { return Object.assign({}, DEFAULT_COLORS); }
  }
  function saveColors(value) {
    try { localStorage.setItem('ghazi.signal.colors', JSON.stringify(value)); } catch (_) { /* optional */ }
  }

  function setStatus(text, bad) { el('status').textContent = text; el('status').classList.toggle('bad', !!bad); }

  function fact(parent, label, value, ltr, cls) {
    const box = document.createElement('p');
    box.className = 'fact' + (ltr ? ' ltr' : '');
    const span = document.createElement('span'); span.textContent = label;
    const b = document.createElement('b'); b.textContent = value;
    if (cls) { b.className = 'state ' + cls; }
    box.append(span, b); parent.append(box);
  }

  function stateClass(state) { return GOOD.has(state) ? 'good' : BAD.has(state) ? 'bad' : WARN.has(state) ? 'warn' : ''; }

  async function load() {
    for (const url of DATA_URLS) {
      try {
        const response = await fetch(url, { cache: 'no-store' });
        if (!response.ok) continue;
        const data = await response.json();
        if (data && Array.isArray(data.signals)) return data;
      } catch (_) { /* try next */ }
    }
    return null;
  }

  function renderFacts(s) {
    const c = s.contract || {};
    el('title').textContent = `${s.underlying || c.root || ''} ${c.side || ''} ${c.strike ?? ''} · ${c.expiration || ''}`;
    el('subtitle').textContent = `القرار: ${s.decision} — سعر العقد نفسه وليس سعر السهم.`;
    const box = el('facts'); box.replaceChildren(); box.hidden = false;
    fact(box, 'الحالة', STATE_AR[s.state] || s.state, false, stateClass(s.state));
    fact(box, 'العقد (OCC)', c.occ || '—', true);
    fact(box, 'النوع', c.side || '—', true);
    fact(box, 'Strike', String(c.strike ?? '—'), true);
    fact(box, 'الانتهاء والتسوية', `${c.expiration || '—'} · ${c.settlement || '—'}`, true);
    fact(box, 'وقت التوصية', nyTime(s.created_at));
    fact(box, 'آخر تداول للعقد', nyTime(c.last_trade_at));
    const grade = (s.data_grade && s.data_grade.grade) || '—';
    fact(box, 'جودة البيانات وقت الإشارة', `${GRADE_AR[grade] || grade} · ${(s.data_grade && s.data_grade.source) || '—'}`);
    fact(box, 'جودة الأدلة', s.evidence_grade || '—');
    if (!pricesBlocked(s)) fact(box, 'سعر الأصل وقت الإشارة', money(s.underlying_price_at_signal), true);
  }

  function renderLevels(s) {
    const panel = el('levels-panel'); panel.hidden = false;
    const box = el('levels'); box.replaceChildren();
    if (pricesBlocked(s)) {
      fact(box, 'المستويات', 'محجوبة: لم يثبت حق النشر العام لمصدر الأسعار');
      return;
    }
    const lv = s.levels; const t = lv.targets || [];
    fact(box, 'منطقة الدخول (Ask)', `${money(lv.entry_zone && lv.entry_zone[0])} – ${money(lv.max_valid_entry)}`, true);
    fact(box, 'الهدف الأول (Bid)', money(t[0]), true);
    fact(box, 'الهدف الثاني (Bid)', money(t[1]), true);
    fact(box, 'الهدف الثالث (Bid)', money(t[2]), true);
    fact(box, 'وقف الخسارة (Bid)', money(lv.stop), true);
    fact(box, 'العائد/المخاطرة للهدف الأول بعد التكاليف', money(lv.reward_risk_t1_after_costs), true);
    if (s.paper && s.paper.fill) fact(box, 'سعر الدخول الورقي', money(s.paper.fill), true);
    if (s.paper && s.paper.return_pct_after_costs != null) fact(box, 'العائد الورقي بعد التكاليف %', money(s.paper.return_pct_after_costs), true);
  }

  function renderHistory(s) {
    el('history-panel').hidden = false;
    const body = el('history'); body.replaceChildren();
    for (const ev of (s.events || []).filter(e => e.type === 'STATE' || e.type === 'CREATED')) {
      const tr = document.createElement('tr');
      for (const value of [nyTime(ev.at), STATE_AR[ev.to] || ev.to || '—', ev.reason || '']) {
        const td = document.createElement('td'); td.textContent = value; tr.append(td);
      }
      body.append(tr);
    }
  }

  function renderUnderlying(s) {
    const symbol = String(s.underlying || '').toUpperCase();
    if (!/^[A-Z][A-Z0-9.-]{0,9}$/.test(symbol)) return;
    el('underlying-panel').hidden = false;
    const link = el('underlying-link');
    link.href = '/?chart=' + encodeURIComponent(symbol);
    link.textContent = `فتح شارت ${symbol} (الأصل الأساسي — ليس العقد)`;
  }

  function renderChart(s) {
    el('chart-panel').hidden = false;
    const unavailable = el('chart-unavailable');
    const holder = el('chart');
    const candles = pricesBlocked(s) ? [] : buildCandles(s.quote_series, 60);
    if (!candles.length || typeof LightweightCharts === 'undefined') {
      holder.hidden = true; unavailable.hidden = false;
      unavailable.textContent = pricesBlocked(s)
        ? 'DATA UNAVAILABLE — أسعار العقد محجوبة لأن مصدرها لا يملك حق نشر عام موثق. لا نعرض بديلًا تقديريًا.'
        : 'DATA UNAVAILABLE — لا توجد لقطات Bid/Ask مؤرخة كافية لبناء شموع العقد.';
      el('chart-basis').textContent = '';
      el('legend').replaceChildren();
      return;
    }
    holder.hidden = false; unavailable.hidden = true;
    const total = candles.reduce((n, c) => n + c.quotes, 0);
    const lastQ = (s.quote_series || []).slice(-1)[0] || {};
    const ageMin = Math.max(0, (Date.now() - Date.parse(lastQ.t)) / 60000);
    el('chart-basis').textContent = `الشموع مبنية من منتصف Bid/Ask لـ ${total} لقطة مؤرخة (دقيقة لكل شمعة) — ليست صفقات منفذة، والحجم غير متاح من هذه اللقطات. آخر لقطة قبل ${ageMin.toFixed(0)} دقيقة؛ التحديث كل دقيقة وليس لحظيًا.`;
    const pal = colors();
    if (!chart) {
      chart = LightweightCharts.createChart(holder, {
        autoSize: true,
        layout: { background: { color: '#0b1b2d' }, textColor: '#aec0d6', fontFamily: 'Tahoma, Arial, sans-serif' },
        grid: { vertLines: { color: '#16283d' }, horzLines: { color: '#16283d' } },
        timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 4 },
        rightPriceScale: { borderColor: '#30435b' },
        localization: { timeFormatter: t => new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York',
          hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(t * 1000)) + ' NY' },
      });
    } else if (candleSeries) { chart.removeSeries(candleSeries); }
    candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
      upColor: pal.up, downColor: pal.down, borderUpColor: pal.up, borderDownColor: pal.down,
      wickUpColor: pal.up, wickDownColor: pal.down,
    });
    candleSeries.setData(candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
    const lv = s.levels; const t = lv.targets || [];
    const line = (price, color, title, style) => { if (Number.isFinite(price)) candleSeries.createPriceLine({
      price, color, title, lineWidth: 2, lineStyle: style, axisLabelVisible: true }); };
    line(lv.entry_reference, pal.entry, 'دخول', 0);
    line(lv.max_valid_entry, pal.entry, 'أقصى دخول', 2);
    line(t[0], pal.target, 'T1', 2); line(t[1], pal.target, 'T2', 2); line(t[2], pal.target, 'T3', 2);
    line(lv.stop, pal.stop, 'وقف', 0);
    if (s.paper && s.paper.fill) line(s.paper.fill, pal.entry, 'دخول ورقي', 1);
    const markers = [];
    const at = iso => Math.floor(Date.parse(iso) / 60000) * 60;
    const first = candles[0].time, lastTime = candles[candles.length - 1].time;
    const clamp = x => Math.min(lastTime, Math.max(first, x));
    if (s.created_at) markers.push({ time: clamp(at(s.created_at)), position: 'belowBar', color: pal.entry, shape: 'arrowUp', text: 'إشارة' });
    for (const ev of s.events || []) {
      if (ev.type !== 'STATE') continue;
      if (/^TARGET_/.test(ev.to)) markers.push({ time: clamp(at(ev.at)), position: 'aboveBar', color: pal.target, shape: 'circle', text: ev.to.replace('TARGET_', 'T') });
      if (ev.to === 'STOPPED' || ev.to === 'INVALIDATED') markers.push({ time: clamp(at(ev.at)), position: 'aboveBar', color: pal.stop, shape: 'square', text: ev.to === 'STOPPED' ? 'وقف' : 'إلغاء' });
    }
    if (typeof LightweightCharts.createSeriesMarkers === 'function') {
      LightweightCharts.createSeriesMarkers(candleSeries, markers.sort((a, b) => a.time - b.time));
    }
    chart.timeScale().fitContent();
    const legend = el('legend'); legend.replaceChildren();
    for (const [label, color] of [['منطقة الدخول', pal.entry], ['الأهداف', pal.target], ['الوقف', pal.stop]]) {
      const li = document.createElement('li'); const i = document.createElement('i'); i.style.background = color;
      li.append(i, document.createTextNode(label)); legend.append(li);
    }
  }

  function bindSettings() {
    const form = el('settings');
    const toggle = el('settings-toggle');
    toggle.addEventListener('click', () => {
      form.hidden = !form.hidden; toggle.setAttribute('aria-expanded', String(!form.hidden));
    });
    const pal = colors();
    for (const name of Object.keys(DEFAULT_COLORS)) {
      form.elements[name].value = pal[name];
      form.elements[name].addEventListener('input', () => {
        const next = colors(); next[name] = form.elements[name].value; saveColors(next);
        if (lastSignal) renderChart(lastSignal);
      });
    }
    el('settings-reset').addEventListener('click', () => {
      saveColors({}); for (const n of Object.keys(DEFAULT_COLORS)) form.elements[n].value = DEFAULT_COLORS[n];
      if (lastSignal) renderChart(lastSignal);
    });
  }

  async function refresh(id) {
    const data = await load();
    if (!data) { setStatus('تعذر قراءة سجل التوصيات المنشور. لا نعرض بيانات بديلة.', true); return; }
    const s = data.signals.find(row => row && row.signal_id === id);
    if (!s) { setStatus('هذه التوصية غير موجودة في السجل المنشور (قد لا يكون السجل مفعّلًا بعد، أو انتهت مدة الاحتفاظ).', true); return; }
    lastSignal = s;
    const generated = Date.parse(data.generated_at);
    const age = Number.isFinite(generated) ? Math.round((Date.now() - generated) / 60000) : null;
    setStatus(`السجل محدث قبل ${age == null ? '—' : age} دقيقة. ${s.display && s.display.note_ar ? s.display.note_ar : ''}`, false);
    renderFacts(s); renderLevels(s); renderChart(s); renderHistory(s); renderUnderlying(s);
  }

  function start() {
    const id = signalIdFrom(window.location);
    if (!id) { setStatus('رابط التوصية غير صالح.', true); return; }
    bindSettings();
    refresh(id);
    setInterval(() => { if (!document.hidden) refresh(id); }, POLL_MS);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
}());
