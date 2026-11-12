/* GHAZI RADAR PRO — platform alpha UI.
 * Rendering rule: user and server text is inserted with textContent only (no innerHTML),
 * so stored values cannot inject markup. Authorization is enforced by the server;
 * the UI only hides what the server would refuse anyway.
 */
'use strict';

const state = { user: null, csrf: null, plans: null };
const VIEWS = {};
const STATUS_AR = { AVAILABLE: 'متاح', NOT_AVAILABLE: 'غير متاح', RECENT: 'حديث', STALE: 'قديم', UNKNOWN: 'غير معروف' };
const TREND_AR = { UP: 'صاعد', DOWN: 'هابط', MIXED: 'مختلط', INSUFFICIENT: 'بيانات غير كافية', UNAVAILABLE: 'غير متاح' };
const FRAME_AR = { weekly: 'الأسبوعي', daily: 'اليومي', '4h': '4 ساعات', '1h': 'الساعة', '15m': '15 دقيقة', '5m': '5 دقائق' };
const OUTCOME_AR = { TARGET: 'هدف', TARGET_GAP: 'هدف (فجوة)', STOP: 'وقف', STOP_GAP: 'وقف (فجوة)', AMBIGUOUS: 'غامضة',
  SIGNAL_EXIT: 'خروج بالإشارة', TIME_EXIT: 'خروج زمني', OPEN_AT_END: 'مفتوحة عند نهاية البيانات' };

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const fmt = (v, d = 2) => (typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('en-US', { maximumFractionDigits: d }) : (v ?? '—'));
const utc = (iso) => (iso ? `${String(iso).slice(0, 16).replace('T', ' ')} UTC` : '—');
const badge = (text, kind) => h('span', { class: `badge ${kind || ''}` }, text);

async function api(method, path, body) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET' && state.csrf) headers['X-CSRF-Token'] = state.csrf;
  const res = await fetch(path, { method, headers, credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body) });
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const err = new Error((data && data.message_ar) || `خطأ ${res.status}`);
    err.status = res.status; err.data = data;
    throw err;
  }
  return data;
}

function toast(msg, bad) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = `toast${bad ? ' bad' : ''}`; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, 5000);
}

async function guarded(btn, fn) {
  if (btn) btn.disabled = true;
  try { return await fn(); } catch (e) {
    if (e.status === 401) { state.user = null; renderWho(); }
    toast(e.message, true);
  } finally { if (btn) btn.disabled = false; }
  return undefined;
}

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    out[el.name] = el.type === 'checkbox' ? el.checked : el.value;
  }
  return out;
}

/* ------------------------------------------------------------ session */

async function loadMe() {
  try {
    const me = await api('GET', '/api/me');
    state.user = me.user; state.csrf = me.csrf_token;
  } catch (_) { state.user = null; state.csrf = null; }
  renderWho();
}

function renderWho() {
  const who = document.getElementById('who');
  who.replaceChildren();
  if (state.user) {
    // Element.append() renders null as the text "null", so filter it out.
    who.append(...[h('span', {}, state.user.display_name || state.user.email),
      badge(state.user.plan.name_ar, 'ok'),
      state.user.email_verified ? null : badge('البريد غير مؤكد', 'warn'),
      h('button', { class: 'link', onclick: logout }, 'خروج')].filter(Boolean));
  } else {
    who.append(h('a', { href: '#login', class: 'btn' }, 'دخول / تسجيل'));
  }
  document.querySelectorAll('[data-auth]').forEach((a) => a.classList.toggle('locked', !state.user));
  document.querySelectorAll('[data-admin]').forEach((a) => { a.hidden = !(state.user && state.user.role === 'admin'); });
}

async function logout() {
  await guarded(null, () => api('POST', '/api/auth/logout', {}));
  state.user = null; state.csrf = null; renderWho(); location.hash = '#dashboard';
}

function needLogin(view) {
  view.append(h('div', { class: 'card' }, h('h1', {}, 'يلزم تسجيل الدخول'),
    h('p', { class: 'lead' }, 'هذا القسم خاص بحسابك؛ بياناتك لا يراها غيرك.'),
    h('a', { class: 'btn', href: '#login' }, 'دخول / تسجيل')));
}

VIEWS.login = (view) => {
  const msg = h('p', { class: 'error', role: 'alert' });
  const login = h('form', { class: 'card', onsubmit: async (e) => {
    e.preventDefault(); msg.textContent = '';
    const btn = e.submitter;
    await guarded(btn, async () => {
      const out = await api('POST', '/api/auth/login', formData(e.target));
      state.user = out.user; state.csrf = out.csrf_token; renderWho(); location.hash = '#dashboard';
    });
  } }, h('h2', {}, 'تسجيل الدخول'),
  h('label', {}, 'البريد الإلكتروني', h('input', { name: 'email', type: 'email', class: 'ltr', autocomplete: 'email', required: true })),
  h('label', {}, 'كلمة المرور', h('input', { name: 'password', type: 'password', autocomplete: 'current-password', required: true })),
  h('button', { class: 'primary', type: 'submit' }, 'دخول'), msg);

  const reg = h('form', { class: 'card', onsubmit: async (e) => {
    e.preventDefault();
    await guarded(e.submitter, async () => {
      const out = await api('POST', '/api/auth/register', formData(e.target));
      toast(out.message_ar);
      if (out.dev_verification_token) {
        await api('POST', '/api/auth/verify', { token: out.dev_verification_token });
        toast('وضع التطوير: تم تأكيد البريد تلقائيًا. سجّل الدخول الآن.');
      }
      e.target.reset();
    });
  } }, h('h2', {}, 'حساب جديد'),
  h('label', {}, 'الاسم الظاهر', h('input', { name: 'display_name', maxlength: 60, autocomplete: 'nickname' })),
  h('label', {}, 'البريد الإلكتروني', h('input', { name: 'email', type: 'email', class: 'ltr', autocomplete: 'email', required: true })),
  h('label', {}, 'كلمة المرور (10 أحرف على الأقل، حروف وأرقام)',
    h('input', { name: 'password', type: 'password', minlength: 10, autocomplete: 'new-password', required: true })),
  h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'consent', required: true }),
    h('span', {}, 'قرأت ', h('a', { href: '#privacy' }, 'إشعار الخصوصية وحدود الخدمة'), ' وأوافق عليه.')),
  h('button', { class: 'primary', type: 'submit' }, 'إنشاء الحساب'));

  const reset = h('form', { class: 'card', onsubmit: async (e) => {
    e.preventDefault();
    await guarded(e.submitter, async () => {
      const data = formData(e.target);
      if (data.token) {
        await api('POST', '/api/auth/reset', { token: data.token, password: data.password });
        toast('تم تغيير كلمة المرور؛ سجّل الدخول.');
      } else {
        const out = await api('POST', '/api/auth/reset-request', { email: data.email });
        toast(out.message_ar);
        if (out.dev_reset_token) e.target.elements.token.value = out.dev_reset_token;
      }
    });
  } }, h('h2', {}, 'نسيت كلمة المرور'),
  h('label', {}, 'البريد الإلكتروني', h('input', { name: 'email', type: 'email', class: 'ltr' })),
  h('label', {}, 'رمز إعادة التعيين (من البريد)', h('input', { name: 'token', class: 'ltr', autocomplete: 'one-time-code' })),
  h('label', {}, 'كلمة مرور جديدة', h('input', { name: 'password', type: 'password', autocomplete: 'new-password' })),
  h('button', { type: 'submit' }, 'إرسال'));
  view.append(h('h1', {}, 'الدخول إلى المنصة'), h('div', { class: 'grid' }, login, reg, reset));
};

/* ------------------------------------------------------------ dashboard */

VIEWS.dashboard = async (view) => {
  const d = await api('GET', '/api/dashboard');
  const p = d.pipeline || {};
  const pipe = h('div', { class: 'card' }, h('h2', {}, 'حالة خط البيانات'),
    h('dl', { class: 'kv' },
      h('dt', {}, 'الحالة'), h('dd', {}, badge(p.status === 'ok' ? 'سليم' : (p.status === 'degraded' ? 'متدهور' : p.status), p.status === 'ok' ? 'ok' : 'warn')),
      h('dt', {}, 'حالة البحث'), h('dd', {}, p.research_status || '—'),
      h('dt', {}, 'مصادر أسهم نشطة'), h('dd', {}, fmt(p.active_stock_sources)),
      h('dt', {}, 'مصادر عقود نشطة'), h('dd', {}, fmt(p.active_option_sources)),
      h('dt', {}, 'آخر إنتاج'), h('dd', { class: 'ltr' }, utc(p.freshness?.generated_at)),
      h('dt', {}, 'العمر'), h('dd', {}, p.freshness?.age_hours != null ? `${fmt(p.freshness.age_hours, 1)} ساعة` : '—')),
    h('p', { class: 'small muted' }, p.freshness?.note_ar || ''));
  const sections = d.sections.map((s) => h('div', { class: 'card' },
    h('div', { class: 'row' }, h('h2', {}, s.title_ar), badge(STATUS_AR[s.state] || s.state, s.state === 'AVAILABLE' ? 'ok' : 'bad')),
    h('p', {}, s.reason_ar || ''),
    s.enable_with ? h('p', { class: 'small muted' }, 'يُفعَّل بـ: ', h('span', { class: 'ltr' }, s.enable_with)) : null,
    h('p', { class: 'small muted' }, 'عمر الملف: ', s.freshness?.age_hours != null ? `${fmt(s.freshness.age_hours, 1)} ساعة` : 'غير معروف',
      ' — ', STATUS_AR[s.freshness?.state] || '')));
  const ws = d.workspace ? h('div', { class: 'card' }, h('h2', {}, 'مساحتك الخاصة'),
    h('div', { class: 'row' }, h('div', {}, h('div', { class: 'stat' }, fmt(d.workspace.watchlists)), h('span', { class: 'muted' }, 'قوائم مراقبة')),
      h('div', {}, h('div', { class: 'stat' }, fmt(d.workspace.datasets)), h('span', { class: 'muted' }, 'ملفات بيانات'))),
    h('div', { class: 'row' }, h('a', { class: 'btn', href: '#watchlists' }, 'قوائمي'), h('a', { class: 'btn', href: '#analysis' }, 'تحليل سهم')))
    : h('div', { class: 'card' }, h('h2', {}, 'مساحتك الخاصة'), h('p', {}, 'سجّل الدخول لحفظ قوائم مراقبة وتحليل بياناتك.'),
      h('a', { class: 'btn', href: '#login' }, 'دخول / تسجيل'));
  view.append(h('h1', {}, 'لوحة التحكم'), h('p', { class: 'lead' }, d.authority.note_ar),
    h('div', { class: 'grid' }, ws, pipe, ...sections));
};

/* ------------------------------------------------------------ watchlists */

VIEWS.watchlists = async (view) => {
  if (!state.user) return needLogin(view);
  const { watchlists } = await api('GET', '/api/watchlists');
  const limits = state.user.plan.limits;
  const create = h('form', { class: 'card', onsubmit: async (e) => {
    e.preventDefault();
    await guarded(e.submitter, async () => { await api('POST', '/api/watchlists', formData(e.target)); route(); });
  } }, h('h2', {}, 'قائمة جديدة'),
  h('p', { class: 'small muted' }, `خطتك تسمح بـ ${limits.watchlists} قائمة و${limits.symbols_per_watchlist} رمزًا لكل قائمة.`),
  h('div', { class: 'row' }, h('input', { name: 'name', maxlength: 60, required: true, placeholder: 'مثال: قادة التقنية', 'aria-label': 'اسم القائمة' }),
    h('button', { class: 'primary', type: 'submit' }, 'إنشاء')));
  const cards = watchlists.map((wl) => {
    const chips = h('div', { class: 'chips' }, wl.symbols.length ? wl.symbols.map((s) => h('span', { class: 'chip' }, s.symbol,
      h('button', { 'aria-label': `حذف ${s.symbol}`, onclick: (e) => guarded(e.currentTarget, async () => {
        await api('DELETE', `/api/watchlists/${wl.id}/symbols/${encodeURIComponent(s.symbol)}`); route(); }) }, '×')))
      : h('span', { class: 'muted' }, 'لا رموز بعد.'));
    const add = h('form', { class: 'row', onsubmit: async (e) => {
      e.preventDefault();
      await guarded(e.submitter, async () => { await api('POST', `/api/watchlists/${wl.id}/symbols`, formData(e.target)); route(); });
    } }, h('input', { name: 'symbol', class: 'ltr', maxlength: 10, required: true, placeholder: 'NVDA', 'aria-label': 'رمز السهم',
      autocapitalize: 'characters' }), h('button', { type: 'submit' }, 'إضافة'));
    return h('div', { class: 'card' },
      h('div', { class: 'row' }, h('h2', {}, wl.name), badge(`${wl.symbols.length} رمز`)),
      chips, h('h3', {}, 'إضافة رمز'), add,
      h('div', { class: 'row' },
        h('a', { class: 'btn', href: `#research?watchlist=${wl.id}` }, 'أخبار ومحفزات القائمة'),
        h('button', { onclick: (e) => guarded(e.currentTarget, async () => {
          const name = prompt('الاسم الجديد', wl.name);
          if (name) { await api('PATCH', `/api/watchlists/${wl.id}`, { name }); route(); }
        }) }, 'إعادة تسمية'),
        h('button', { class: 'danger', onclick: (e) => guarded(e.currentTarget, async () => {
          if (confirm(`حذف القائمة «${wl.name}»؟`)) { await api('DELETE', `/api/watchlists/${wl.id}`); route(); }
        }) }, 'حذف')));
  });
  view.append(h('h1', {}, 'قوائم المراقبة'), h('p', { class: 'lead' }, 'قوائمك محفوظة في حسابك ولا يراها غيرك.'),
    h('div', { class: 'grid' }, create, ...(cards.length ? cards : [h('div', { class: 'empty' }, 'لا توجد قوائم بعد.')])));
};

/* ------------------------------------------------------------ analysis */

function uploadForm(after) {
  return h('form', { class: 'card', onsubmit: async (e) => {
    e.preventDefault();
    const data = formData(e.target);
    const file = e.target.elements.file.files[0];
    if (!file) return toast('اختر ملف CSV.', true);
    if (file.size > 1900000) return toast('الملف أكبر من 1.9 ميغابايت.', true);
    await guarded(e.submitter, async () => {
      await api('POST', '/api/datasets', { symbol: data.symbol, label: data.label, csv: await file.text(), rights_attested: data.rights_attested });
      toast('رُفع الملف وتحقق من اتساق الشموع.'); after();
    });
  } }, h('h2', {}, 'رفع بيانات يومية (CSV)'),
  h('p', { class: 'small muted' }, 'الأعمدة: date, open, high, low, close, volume. تُرفض الملفات ذات الشموع غير المتسقة مع رقم السطر.'),
  h('div', { class: 'fields' },
    h('label', {}, 'الرمز', h('input', { name: 'symbol', class: 'ltr', maxlength: 10, required: true, placeholder: 'AAPL' })),
    h('label', {}, 'وصف المصدر', h('input', { name: 'label', maxlength: 80, placeholder: 'مثال: تصدير وسيطي الخاص' }))),
  h('label', {}, 'الملف', h('input', { name: 'file', type: 'file', accept: '.csv,text/csv', required: true })),
  h('label', { class: 'check' }, h('input', { type: 'checkbox', name: 'rights_attested', required: true }),
    h('span', {}, 'أقر بأن هذه البيانات ملكي أو أملك حق استخدامها لتحليلي الخاص، وأنها لن تُعرض لغيري.')),
  h('button', { class: 'primary', type: 'submit' }, 'رفع'));
}

function renderCard(out) {
  const card = out.card;
  if (!card.available) return h('div', { class: 'card wide' }, h('h2', {}, out.symbol), h('p', { class: 'error' }, `لا قراءة: ${card.reason}`));
  const frames = Object.entries(card.interpretation.frames).map(([k, f]) => h('tr', {},
    h('td', {}, FRAME_AR[k] || k), h('td', {}, badge(TREND_AR[f.trend] || f.trend, f.trend === 'UP' ? 'ok' : f.trend === 'DOWN' ? 'bad' : '')),
    h('td', {}, f.basis || '—'), h('td', { class: 'ltr' }, f.last_bar_end || '—')));
  const levels = card.observed.levels.map((lv) => h('tr', {}, h('td', {}, lv.method), h('td', { class: 'num' }, fmt(lv.value, 4)), h('td', { class: 'ltr' }, lv.bar)));
  return h('div', { class: 'card wide' },
    h('div', { class: 'row' }, h('h2', {}, `${card.symbol} — قراءة على بياناتك`), badge('بلا احتمال نجاح', 'warn'), badge('خاص بك')),
    h('p', { class: 'small muted' }, `بيانات حتى ${card.data_as_of}. ${card.delay_note || ''}`),
    h('h3', {}, 'الفريمات'), h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'الفريم'), h('th', {}, 'الاتجاه'), h('th', {}, 'الأساس'), h('th', {}, 'آخر شمعة'))), h('tbody', {}, frames))),
    h('p', { class: 'small muted' }, card.interpretation.agreement?.note || ''),
    h('h3', {}, 'المستويات (بطريقة قياس معلنة)'), h('div', { class: 'table-wrap' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', {}, 'الطريقة'), h('th', {}, 'القيمة'), h('th', {}, 'الشمعة'))), h('tbody', {}, levels))),
    h('h3', {}, 'القراءة (قالب ثابت من الأرقام المحسوبة)'), h('pre', { class: 'reading' }, out.text_ar),
    out.text_numbers_supported ? h('p', { class: 'small muted' }, '✓ كل رقم في النص موجود في البطاقة المحسوبة.') : h('p', { class: 'error' }, 'تحذير: النص يحوي أرقامًا غير مدعومة.'));
}

VIEWS.analysis = async (view) => {
  if (!state.user) return needLogin(view);
  const { datasets } = await api('GET', '/api/datasets');
  const result = h('div', { class: 'grid' });
  const list = h('div', { class: 'card' }, h('h2', {}, 'ملفاتك'),
    datasets.length ? h('ul', { class: 'items' }, datasets.map((d) => h('li', {},
      h('div', { class: 'row' }, h('strong', { class: 'ltr' }, d.symbol), h('span', { class: 'muted' }, d.label)),
      h('div', { class: 'small muted' }, `${d.bar_count} شمعة من ${d.first_date} إلى ${d.last_date}`),
      h('div', { class: 'row' },
        h('button', { class: 'primary', onclick: (e) => guarded(e.currentTarget, async () => {
          const out = await api('GET', `/api/datasets/${d.id}/analysis`); result.replaceChildren(renderCard(out));
          result.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }) }, 'حلّل'),
        h('button', { class: 'danger', onclick: (e) => guarded(e.currentTarget, async () => {
          if (confirm('حذف الملف وكل اختباراته؟')) { await api('DELETE', `/api/datasets/${d.id}`); route(); } }) }, 'حذف')))))
      : h('div', { class: 'empty' }, 'لا ملفات بعد.'));
  view.append(h('h1', {}, 'تحليل الأسهم والمؤشرات'),
    h('p', { class: 'lead' }, 'لا يوجد حاليًا مصدر أسعار بحق عرض تجاري موثق، لذا يعمل التحليل على بيانات ترفعها أنت لنفسك، بمحرك التحليل نفسه المستخدم في الرادار (EMA20/50، ATR14، مستويات الجلسة والأسبوع السابقين، سيناريوهات مشروطة).'),
    h('div', { class: 'grid' }, uploadForm(route), list), result);
};

/* ------------------------------------------------------------ research */

VIEWS.research = async (view, params) => {
  let wls = [];
  if (state.user) wls = (await api('GET', '/api/watchlists')).watchlists;
  const q = params.get('watchlist');
  const data = await api('GET', `/api/research${q ? `?watchlist=${encodeURIComponent(q)}` : ''}`);
  const filter = state.user ? h('div', { class: 'row' }, h('label', {}, 'تصفية حسب القائمة',
    h('select', { onchange: (e) => { location.hash = e.target.value ? `#research?watchlist=${e.target.value}` : '#research'; } },
      h('option', { value: '' }, 'كل العناصر'), wls.map((w) => h('option', { value: w.id, selected: String(w.id) === q }, w.name))))) : null;
  const items = data.items.map((it) => h('li', {},
    h('div', { class: 'row' }, h('strong', { class: 'ltr' }, it.symbol || '—'), h('span', { class: 'muted ltr' }, it.published_at),
      badge(it.source || 'مصدر غير مسمى'), it.mode === 'FULL' ? badge('نص معروض', 'ok') : badge('رابط رسمي فقط', 'warn')),
    it.title ? h('p', {}, it.title) : h('p', { class: 'small muted' }, it.rights.reason_ar),
    h('a', { href: it.url, target: '_blank', rel: 'noopener noreferrer nofollow', class: 'ltr' }, 'افتح المصدر الرسمي ↗'),
    h('p', { class: 'small muted' }, it.impact_note_ar)));
  view.append(h('h1', {}, 'مركز الأبحاث: الأخبار والمحفزات'), h('p', { class: 'lead' }, data.note_ar), filter,
    h('div', { class: 'row small muted' }, `العناصر: ${data.total}`, ' · ', `نص محجوب: ${data.withheld_text}`, ' · ',
      `مستبعد بلا رابط/تاريخ: ${data.dropped_unverifiable}`, ' · ', `عمر الملف: ${data.freshness.age_hours ?? '—'} ساعة`),
    items.length ? h('ul', { class: 'items' }, items) : h('div', { class: 'empty' }, 'لا عناصر لهذه التصفية.'));
};

/* ------------------------------------------------------------ backtest lab */

function summaryTable(title, s) {
  const share = s.net_positive_share ? `${s.net_positive_share.count} من ${s.net_positive_share.of}` : (s.insufficient_note_ar || '—');
  return h('div', { class: 'card' }, h('h3', {}, title), h('dl', { class: 'kv' },
    h('dt', {}, 'إشارات'), h('dd', {}, fmt(s.signals)), h('dt', {}, 'صفقات محسومة'), h('dd', {}, fmt(s.resolved)),
    h('dt', {}, 'غامضة (وقف وهدف بنفس الشمعة)'), h('dd', {}, fmt(s.ambiguous_same_bar)),
    h('dt', {}, 'مفتوحة عند النهاية'), h('dd', {}, fmt(s.open_at_end)),
    h('dt', {}, 'صافي موجب'), h('dd', {}, share),
    h('dt', {}, 'متوسط العائد الصافي %'), h('dd', { class: 'ltr' }, fmt(s.mean_net_return_pct, 3)),
    h('dt', {}, 'الوسيط %'), h('dd', { class: 'ltr' }, fmt(s.median_net_return_pct, 3)),
    h('dt', {}, 'العائد المركب %'), h('dd', { class: 'ltr' }, fmt(s.compounded_net_return_pct, 2)),
    h('dt', {}, 'أقصى تراجع %'), h('dd', { class: 'ltr' }, fmt(s.max_drawdown_pct, 2))),
    s.net_positive_share ? h('p', { class: 'small muted' }, s.net_positive_share.note_ar) : null);
}

function renderBacktest(r) {
  const trades = r.trades.slice(-60).reverse().map((t) => h('tr', {}, h('td', { class: 'ltr' }, t.signal_date), h('td', { class: 'ltr' }, t.entry_date),
    h('td', { class: 'num' }, fmt(t.entry, 2)), h('td', {}, OUTCOME_AR[t.outcome] || t.outcome), h('td', { class: 'ltr' }, t.exit_date),
    h('td', { class: 'num' }, t.net_return_pct != null ? fmt(t.net_return_pct, 2) : '—')));
  return h('div', {},
    h('div', { class: 'row' }, h('h2', {}, `${r.strategy_ar} — ${r.dataset.symbol}`), badge('ليس احتمالًا مستقبليًا', 'warn')),
    h('p', { class: 'small muted' }, `${r.bars} شمعة من ${r.period.from} إلى ${r.period.to}`),
    h('ul', { class: 'small' }, r.assumptions_ar.map((a) => h('li', {}, a))),
    h('div', { class: 'grid' }, summaryTable('كل الفترة', r.all),
      r.split ? summaryTable(`داخل العينة (قبل ${r.split.oos_starts})`, r.split.in_sample) : null,
      r.split ? summaryTable('خارج العينة', r.split.out_of_sample) : null),
    r.cost_sensitivity ? h('div', { class: 'card' }, h('h3', {}, 'حساسية التكاليف'), h('div', { class: 'table-wrap' }, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'مضاعف التكلفة'), h('th', {}, 'صفقات'), h('th', {}, 'متوسط %'), h('th', {}, 'مركب %'), h('th', {}, 'أقصى تراجع %'))),
      h('tbody', {}, r.cost_sensitivity.map((c) => h('tr', {}, h('td', { class: 'num' }, `×${c.cost_multiplier}`), h('td', { class: 'num' }, fmt(c.resolved)),
        h('td', { class: 'num' }, fmt(c.mean_net_return_pct, 3)), h('td', { class: 'num' }, fmt(c.compounded_net_return_pct, 2)), h('td', { class: 'num' }, fmt(c.max_drawdown_pct, 2)))))))) : null,
    h('h3', {}, 'آخر الصفقات'), h('div', { class: 'table-wrap' }, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'الإشارة'), h('th', {}, 'الدخول'), h('th', {}, 'سعر الدخول'), h('th', {}, 'النتيجة'), h('th', {}, 'الخروج'), h('th', {}, 'صافي %'))),
      h('tbody', {}, trades))));
}

VIEWS.lab = async (view) => {
  if (!state.user) return needLogin(view);
  const features = new Set(state.user.plan.features);
  if (!features.has('backtest_lab')) {
    view.append(h('h1', {}, 'مختبر الاختبارات التاريخية'), h('div', { class: 'card' },
      h('p', {}, `المختبر غير مشمول في خطة ${state.user.plan.name_ar}. يتحقق الخادم من هذا القيد ولا يكفي إخفاؤه هنا.`),
      h('a', { class: 'btn', href: '#plans' }, 'عرض الخطط')));
    return;
  }
  const [{ datasets }, meta] = await Promise.all([api('GET', '/api/datasets'), api('GET', '/api/backtests')]);
  const out = h('div', {});
  if (!datasets.length) {
    view.append(h('h1', {}, 'مختبر الاختبارات التاريخية'), h('div', { class: 'card' }, h('p', {}, 'ارفع ملف بيانات أولًا من قسم تحليل سهم.'), h('a', { class: 'btn', href: '#analysis' }, 'رفع بيانات')));
    return;
  }
  const paramBox = h('div', { class: 'fields' });
  const strategySel = h('select', { name: 'strategy', onchange: () => drawParams() },
    Object.entries(meta.strategies).map(([k, s]) => h('option', { value: k }, s.name_ar)));
  const LABEL = { fast: 'المتوسط السريع', slow: 'المتوسط البطيء', lookback: 'نافذة القمة (جلسات)', stop_atr: 'الوقف × ATR',
    target_atr: 'الهدف × ATR (0 = بلا هدف)', max_hold: 'أقصى مدة (جلسات)' };
  function drawParams() {
    const s = meta.strategies[strategySel.value];
    paramBox.replaceChildren(...Object.entries(s.params).map(([k, p]) => h('label', {}, LABEL[k] || k,
      h('input', { name: k, type: 'number', step: 'any', min: p.min, max: p.max, value: p.default, class: 'ltr' }))));
  }
  drawParams();
  const form = h('form', { class: 'card', onsubmit: async (e) => {
    e.preventDefault();
    const data = formData(e.target);
    const params = {};
    for (const [k, v] of Object.entries(data)) if (!['dataset_id', 'strategy'].includes(k) && v !== '') params[k] = Number(v);
    await guarded(e.submitter, async () => {
      const r = await api('POST', '/api/backtests', { dataset_id: Number(data.dataset_id), strategy: data.strategy, params });
      out.replaceChildren(renderBacktest(r)); out.scrollIntoView({ behavior: 'smooth' });
    });
  } }, h('h2', {}, 'إعداد الاختبار'),
  h('div', { class: 'fields' },
    h('label', {}, 'البيانات', h('select', { name: 'dataset_id' }, datasets.map((d) => h('option', { value: d.id }, `${d.symbol} — ${d.label}`)))),
    h('label', {}, 'الاستراتيجية', strategySel)),
  paramBox,
  h('div', { class: 'fields' },
    h('label', {}, 'العمولة لكل جهة (نقطة أساس)', h('input', { name: 'commission_bps', type: 'number', step: 'any', min: 0, max: 100, value: 1, class: 'ltr' })),
    h('label', {}, 'الانزلاق لكل جهة (نقطة أساس)', h('input', { name: 'slippage_bps', type: 'number', step: 'any', min: 0, max: 200, value: 5, class: 'ltr' })),
    features.has('backtest_oos_split')
      ? h('label', {}, 'نسبة خارج العينة (0 أو 0.1–0.5)', h('input', { name: 'oos_fraction', type: 'number', step: '0.05', min: 0, max: 0.5, value: 0.3, class: 'ltr' }))
      : h('p', { class: 'small muted' }, 'تقسيم خارج العينة وحساسية التكاليف ضمن خطة برو.')),
  h('button', { class: 'primary', type: 'submit' }, 'شغّل الاختبار'));
  view.append(h('h1', {}, 'مختبر الاختبارات التاريخية'),
    h('p', { class: 'lead' }, `حصتك اليومية: ${state.user.plan.limits.backtests_per_day} اختبارًا. النتائج أعداد مع مقاماتها؛ لا تُعرض نسبة تحت ${30} صفقة.`),
    form, out);
};

/* ------------------------------------------------------------ plans, account, admin */

VIEWS.plans = async (view) => {
  const data = await api('GET', '/api/plans');
  const current = state.user?.plan.code;
  view.append(h('h1', {}, 'الاشتراكات'), h('p', { class: 'lead' }, data.note_ar),
    data.billing_mode !== 'sandbox' ? h('div', { class: 'notice' }, 'التحصيل المالي غير مفعّل. الخطط المدفوعة تُمنح يدويًا من الإدارة لشركاء التجربة فقط.') : h('div', { class: 'notice' }, 'وضع اختبار (sandbox): لا تُسحب أي أموال.'),
    h('div', { class: 'grid' }, data.plans.map((p) => h('div', { class: 'card' },
      h('div', { class: 'row' }, h('h2', {}, p.name_ar), p.code === current ? badge('خطتك', 'ok') : null),
      h('p', { class: 'stat' }, p.price_hypothesis_sar === '0' ? 'مجاني' : `${p.price_hypothesis_sar}`),
      h('p', { class: 'small muted' }, 'ريال سعودي — فرضية تسعير تجريبية'),
      h('ul', {}, p.features_ar.map((f) => h('li', {}, f))),
      h('p', { class: 'small muted' }, `${p.limits.watchlists} قوائم · ${p.limits.symbols_per_watchlist} رمز/قائمة · ${p.limits.datasets} ملفات · ${p.limits.backtests_per_day} اختبار/يوم`),
      h('p', { class: 'small' }, 'لا يشمل أي خطة: إشارات مضمونة، تداولًا آليًا، أو أسعارًا بلا حق عرض.')))));
};

VIEWS.account = async (view) => {
  if (!state.user) return needLogin(view);
  const { sessions } = await api('GET', '/api/sessions');
  const sess = h('div', { class: 'card' }, h('h2', {}, 'الجلسات النشطة'), h('ul', { class: 'items' }, sessions.map((s) => h('li', {},
    h('div', { class: 'small ltr' }, s.user_agent || 'جهاز غير معروف'),
    h('div', { class: 'small muted' }, `آخر نشاط ${s.last_seen_at}`), s.current ? badge('هذا الجهاز', 'ok')
      : h('button', { onclick: (e) => guarded(e.currentTarget, async () => { await api('DELETE', `/api/sessions/${s.id}`); route(); }) }, 'إنهاء')))),
  h('button', { class: 'danger', onclick: (e) => guarded(e.currentTarget, async () => {
    await api('POST', '/api/auth/logout-all', {}); state.user = null; renderWho(); location.hash = '#login'; }) }, 'الخروج من كل الأجهزة'));
  const pw = h('form', { class: 'card', onsubmit: async (e) => {
    e.preventDefault();
    await guarded(e.submitter, async () => { await api('POST', '/api/account/password', formData(e.target)); e.target.reset(); toast('تم التغيير وأُنهيت الجلسات الأخرى.'); });
  } }, h('h2', {}, 'تغيير كلمة المرور'),
  h('label', {}, 'الحالية', h('input', { name: 'current', type: 'password', autocomplete: 'current-password', required: true })),
  h('label', {}, 'الجديدة', h('input', { name: 'new', type: 'password', autocomplete: 'new-password', minlength: 10, required: true })),
  h('button', { type: 'submit' }, 'تغيير'));
  const data = h('div', { class: 'card' }, h('h2', {}, 'بياناتك'),
    h('p', {}, 'نزّل نسخة كاملة من كل ما نحفظه عنك، أو احذف حسابك نهائيًا.'),
    h('a', { class: 'btn', href: '/api/account/export', download: 'ghazi-platform-export.json' }, 'تصدير بياناتي (JSON)'),
    h('form', { onsubmit: async (e) => {
      e.preventDefault();
      if (!confirm('حذف الحساب نهائيًا مع كل القوائم والملفات والاختبارات؟')) return;
      await guarded(e.submitter, async () => { await api('POST', '/api/account/delete', formData(e.target)); state.user = null; renderWho(); location.hash = '#dashboard'; toast('حُذف الحساب.'); });
    } }, h('label', {}, 'كلمة المرور للتأكيد', h('input', { name: 'password', type: 'password', autocomplete: 'current-password', required: true })),
    h('button', { class: 'danger', type: 'submit' }, 'حذف الحساب')));
  view.append(h('h1', {}, 'حسابي'), h('div', { class: 'grid' }, sess, pw, data));
};

VIEWS.admin = async (view) => {
  if (!state.user || state.user.role !== 'admin') return needLogin(view);
  const d = await api('GET', '/api/admin/overview');
  const grant = h('form', { class: 'card', onsubmit: async (e) => {
    e.preventDefault();
    const data = formData(e.target);
    await guarded(e.submitter, async () => { await api('POST', '/api/admin/grant', { user_id: Number(data.user_id), plan: data.plan, days: Number(data.days) }); toast('تم منح الخطة.'); route(); });
  } }, h('h2', {}, 'منح خطة يدويًا (شركاء التجربة)'),
  h('div', { class: 'fields' },
    h('label', {}, 'المستخدم', h('select', { name: 'user_id' }, d.users.map((u) => h('option', { value: u.id }, u.email)))),
    h('label', {}, 'الخطة', h('select', { name: 'plan' }, ['free', 'plus', 'pro'].map((p) => h('option', { value: p }, p)))),
    h('label', {}, 'المدة (أيام)', h('input', { name: 'days', type: 'number', min: 1, max: 366, value: 30, class: 'ltr' }))),
  h('button', { class: 'primary', type: 'submit' }, 'منح'), h('p', { class: 'small muted' }, 'كل منح يُسجَّل في سجل التدقيق.'));
  const users = h('div', { class: 'card wide' }, h('h2', {}, `المستخدمون (${d.users.length})`), h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, ['#', 'البريد', 'الدور', 'الخطة', 'الحالة', 'المصدر', 'نهاية الفترة'].map((t) => h('th', {}, t)))),
    h('tbody', {}, d.users.map((u) => h('tr', {}, h('td', {}, u.id), h('td', { class: 'ltr' }, u.email), h('td', {}, u.role), h('td', {}, u.plan),
      h('td', {}, u.status), h('td', {}, u.source), h('td', { class: 'ltr' }, u.current_period_end || '—')))))));
  const events = h('div', { class: 'card wide' }, h('h2', {}, 'سجل التدقيق (آخر 100)'), h('div', { class: 'table-wrap' }, h('table', {},
    h('thead', {}, h('tr', {}, ['الوقت', 'الإجراء', 'المستخدم', 'المنفذ', 'تفاصيل'].map((t) => h('th', {}, t)))),
    h('tbody', {}, d.audit_events.map((a) => h('tr', {}, h('td', { class: 'ltr' }, a.at), h('td', { class: 'ltr' }, a.action),
      h('td', {}, a.user_id ?? '—'), h('td', {}, a.actor_id ?? '—'), h('td', { class: 'ltr small' }, a.detail_json)))))));
  view.append(h('h1', {}, 'الإدارة'),
    h('div', { class: 'grid' }, h('div', { class: 'card' }, h('h2', {}, 'توزيع الخطط'),
      h('dl', { class: 'kv' }, Object.entries(d.plan_counts).flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)])),
      h('p', { class: 'small muted' }, `أحداث الفوترة المسجلة: ${d.billing_events.length}`)), grant, users, events));
};

VIEWS.privacy = (view) => {
  view.append(h('h1', {}, 'الخصوصية وحدود الخدمة'), h('div', { class: 'card' },
    h('h2', {}, 'ما نحفظه'), h('ul', {},
      h('li', {}, 'بريدك واسمك الظاهر وتجزئة كلمة المرور (scrypt) — لا نحفظ كلمة المرور نفسها.'),
      h('li', {}, 'قوائم المراقبة وملفات البيانات التي ترفعها ونتائج اختباراتك؛ لا يراها غيرك.'),
      h('li', {}, 'سجل تدقيق داخلي (دخول، تغييرات، منح خطط) دون كلمات مرور أو رموز.')),
    h('h2', {}, 'حقوقك'), h('ul', {}, h('li', {}, 'تنزيل نسخة كاملة من بياناتك في أي وقت.'), h('li', {}, 'حذف الحساب وكل بياناته نهائيًا.')),
    h('h2', {}, 'حدود الخدمة'), h('ul', {},
      h('li', {}, 'المنصة أداة بحث ومعلومات، وليست استشارة استثمارية مرخصة ولا توصية مخصصة.'),
      h('li', {}, 'لا تنفذ المنصة أوامر تداول، ولا تقدم احتمالات نجاح؛ نتائج الاختبارات التاريخية لا تضمن المستقبل.'),
      h('li', {}, 'لا تُعرض بيانات سوق لا يملك مصدرها حق عرض تجاري موثق.')),
    h('p', { class: 'small muted' }, 'نسخة الإشعار: 2026-11-12.alpha — مسودة تحتاج مراجعة قانونية قبل الإطلاق.')));
};

/* ------------------------------------------------------------ router */

async function route() {
  const [name, query] = (location.hash.slice(1) || 'dashboard').split('?');
  const viewName = VIEWS[name] ? name : 'dashboard';
  document.querySelectorAll('.tabs a').forEach((a) => {
    if (a.dataset.view === viewName) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  const view = document.getElementById('view');
  view.replaceChildren(h('p', { class: 'muted' }, 'جارٍ التحميل…'));
  const fresh = h('div', {});
  try {
    await VIEWS[viewName](fresh, new URLSearchParams(query || ''));
    view.replaceChildren(fresh);
  } catch (e) {
    if (e.status === 401) { state.user = null; renderWho(); }
    view.replaceChildren(h('div', { class: 'card' }, h('p', { class: 'error' }, e.message)));
  }
  document.title = `غازي رادار برو — ${document.querySelector('.tabs a[aria-current]')?.textContent || 'المنصة'}`;
}

window.addEventListener('hashchange', route);
document.addEventListener('DOMContentLoaded', async () => { await loadMe(); route(); });
