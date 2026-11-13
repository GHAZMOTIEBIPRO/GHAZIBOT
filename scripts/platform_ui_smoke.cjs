#!/usr/bin/env node
// End-to-end smoke for the platform alpha against a running local server.
// Usage: GHAZI_PLATFORM_URL=http://127.0.0.1:8765 node scripts/platform_ui_smoke.cjs [screenshot_dir]
// The server must run on a FRESH database with GHAZI_PLATFORM_ENV=development GHAZI_PLATFORM_ENABLED=1
// GHAZI_PLATFORM_DEV=1 GHAZI_PLATFORM_INSECURE_COOKIES=1 (dev mode auto-confirms e-mail in the UI), and
// this script must see the same GHAZI_PLATFORM_DB / GHAZI_PLATFORM_ENV: it grants the owner role with
// `python -m ghazi_platform grant-owner`, the only path to admin.
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { chromium, devices } = require('playwright');

const BASE = process.env.GHAZI_PLATFORM_URL || 'http://127.0.0.1:8765';
const OUT = process.argv[2] || '';
const PASSWORD = 'smoke-pass-2026';

function csv(n) {
  const rows = ['date,open,high,low,close,volume'];
  let d = new Date(Date.UTC(2025, 0, 6));
  let price = 100;
  for (let i = 0; i < n;) {
    if (d.getUTCDay() !== 0 && d.getUTCDay() !== 6) {
      const wave = ((i * 0.37) % 7) - 3.2;
      const o = price;
      const c = Math.max(1, price + wave * 0.6 + ((Math.floor(i / 40) % 2 === 0) ? 0.15 : -0.12));
      rows.push(`${d.toISOString().slice(0, 10)},${o.toFixed(2)},${(Math.max(o, c) + 0.8).toFixed(2)},${(Math.min(o, c) - 0.8).toFixed(2)},${c.toFixed(2)},${1000 + i}`);
      price = c; i += 1;
    }
    d = new Date(d.getTime() + 86400000);
  }
  return rows.join('\n');
}

const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok: Boolean(ok), detail: detail || '' });
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ` — ${detail}` : ''}`);
}

async function shot(page, name) {
  if (!OUT) return;
  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
}

async function noHorizontalScroll(page, label) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(`${label}: no horizontal page scroll`, overflow <= 1, `overflow ${overflow}px`);
}

async function signup(page, email, name) {
  await page.goto(`${BASE}/#login`);
  const reg = page.locator('form', { hasText: 'حساب جديد' });
  await reg.locator('input[name=display_name]').fill(name);
  await reg.locator('input[name=email]').fill(email);
  await reg.locator('input[name=password]').fill(PASSWORD);
  await reg.locator('input[name=consent]').check();
  await reg.locator('button[type=submit]').click();
  await page.locator('#toast', { hasText: 'سجّل الدخول' }).waitFor();
  const login = page.locator('form', { hasText: 'تسجيل الدخول' });
  await login.locator('input[name=email]').fill(email);
  await login.locator('input[name=password]').fill(PASSWORD);
  await login.locator('button[type=submit]').click();
  await page.waitForURL(/#dashboard/);
  await page.locator('#who', { hasText: 'خروج' }).waitFor();
}

(async () => {
  const browser = await chromium.launch();
  const tmpCsv = path.join(require('os').tmpdir(), `ghazi-smoke-${process.pid}.csv`);
  fs.writeFileSync(tmpCsv, csv(260));
  const consoleErrors = [];
  try {
    // ---------------- mobile, anonymous + user flow
    const mobile = await browser.newContext({ ...devices['iPhone 13'], locale: 'ar' });
    const page = await mobile.newPage();
    // Expected 401/403 API answers are logged by the browser as resource errors; only script errors count.
    page.on('console', (m) => {
      if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) consoleErrors.push(m.text());
    });
    page.on('pageerror', (e) => consoleErrors.push(String(e)));

    await page.goto(`${BASE}/#dashboard`);
    await page.locator('h1', { hasText: 'لوحة التحكم' }).waitFor();
    check('anonymous dashboard renders', true);
    check('page is RTL Arabic', await page.evaluate(() => document.documentElement.dir === 'rtl' && document.documentElement.lang === 'ar'));
    const dashText = await page.locator('#view').innerText();
    check('prices section says NOT AVAILABLE', dashText.includes('أسعار الأسهم والعقود') && dashText.includes('غير متاح'));
    await noHorizontalScroll(page, 'mobile dashboard');
    await shot(page, '01-mobile-dashboard-anonymous');

    await page.goto(`${BASE}/#watchlists`);
    await page.locator('h1', { hasText: 'يلزم تسجيل الدخول' }).waitFor();
    check('private section asks for login when anonymous', true);

    await signup(page, 'alice@example.test', 'أليس');
    check('register + login through the UI', true);

    await page.goto(`${BASE}/#watchlists`);
    const create = page.locator('form', { hasText: 'قائمة جديدة' });
    await create.locator('input[name=name]').fill('قادة التقنية');
    await create.locator('button[type=submit]').click();
    await page.locator('h2', { hasText: 'قادة التقنية' }).waitFor();
    for (const sym of ['NVDA', 'AAPL', 'LLY']) {
      const card = page.locator('.card', { has: page.locator('h2', { hasText: 'قادة التقنية' }) });
      await card.locator('input[name=symbol]').fill(sym);
      await card.locator('form button[type=submit]').click();
      await page.locator('.chip', { hasText: sym }).waitFor();
    }
    check('watchlist created with 3 symbols', (await page.locator('.chip').count()) === 3);
    await page.reload();
    await page.locator('.chip', { hasText: 'LLY' }).waitFor();
    check('watchlist persists after reload', true);
    await noHorizontalScroll(page, 'mobile watchlists');
    await shot(page, '02-mobile-watchlists');

    // free plan limit enforced by the server, surfaced in the UI
    await create.locator('input[name=name]').fill('قائمة ثانية');
    await create.locator('button[type=submit]').click();
    await page.locator('#toast', { hasText: 'حد خطتك' }).waitFor();
    check('free plan watchlist limit shown from server', true);

    await page.goto(`${BASE}/#research`);
    await page.locator('h1', { hasText: 'مركز الأبحاث' }).waitFor();
    const select = page.locator('select');
    await select.selectOption({ label: 'قادة التقنية' });
    await page.waitForURL(/watchlist=/);
    await page.locator('h1', { hasText: 'مركز الأبحاث' }).waitFor();
    const researchText = await page.locator('#view').innerText();
    check('research filtered by watchlist', researchText.includes('LLY') || researchText.includes('لا عناصر'));
    await shot(page, '03-mobile-research');

    await page.goto(`${BASE}/#analysis`);
    const up = page.locator('form', { hasText: 'رفع بيانات' });
    await up.locator('input[name=symbol]').fill('NVDA');
    await up.locator('input[name=label]').fill('ملف اختبار اصطناعي');
    await up.locator('input[name=file]').setInputFiles(tmpCsv);
    await up.locator('input[name=rights_attested]').check();
    await up.locator('button[type=submit]').click();
    await page.locator('li', { hasText: '260 شمعة' }).waitFor();
    await page.locator('button', { hasText: 'حلّل' }).first().click();
    await page.locator('h2', { hasText: 'قراءة على بياناتك' }).waitFor();
    const card = await page.locator('#view').innerText();
    check('analysis card renders from existing engine', card.includes('الفريمات') && card.includes('بلا احتمال نجاح'));
    check('analysis text numbers verified', card.includes('كل رقم في النص موجود'));
    await noHorizontalScroll(page, 'mobile analysis');
    await shot(page, '04-mobile-analysis');

    await page.goto(`${BASE}/#lab`);
    await page.locator('text=غير مشمول في خطة').waitFor();
    check('lab locked on free plan', true);
    await shot(page, '05-mobile-lab-locked');
    await mobile.close();

    // ---------------- desktop, owner grants pro, then lab
    const desk = await browser.newContext({ viewport: { width: 1366, height: 900 }, locale: 'ar' });
    const owner = await desk.newPage();
    owner.on('pageerror', (e) => consoleErrors.push(String(e)));
    await signup(owner, 'owner@example.test', 'المالك');
    // Signing up (even with the owner's address, verified) gives no admin authority.
    check('admin tab hidden before the server-side grant', !(await owner.locator('a[data-view=admin]').isVisible()));
    const before = await owner.evaluate(async () => (await fetch('/api/admin/overview')).status);
    check('admin API is 404 before the server-side grant', before === 404, `status ${before}`);
    // The only way to the admin role: the command line on the host.
    execFileSync('python3', ['-m', 'ghazi_platform', 'grant-owner', '--email', 'owner@example.test'],
      { cwd: path.join(__dirname, '..'), env: process.env, stdio: 'pipe' });
    await owner.goto(`${BASE}/#dashboard`);
    await owner.reload();
    check('grant signed the owner out', await owner.locator('#who a', { hasText: 'دخول' }).isVisible());
    await owner.goto(`${BASE}/#login`);
    const ownerLogin = owner.locator('form', { hasText: 'تسجيل الدخول' });
    await ownerLogin.locator('input[name=email]').fill('owner@example.test');
    await ownerLogin.locator('input[name=password]').fill(PASSWORD);
    await ownerLogin.locator('button[type=submit]').click();
    await owner.locator('#who', { hasText: 'خروج' }).waitFor();
    check('admin tab visible for owner after the grant', await owner.locator('a[data-view=admin]').isVisible());
    await owner.goto(`${BASE}/#admin`);
    const grant = owner.locator('form', { hasText: 'منح خطة' });
    await grant.locator('select[name=user_id]').selectOption({ label: 'alice@example.test' });
    await grant.locator('select[name=plan]').selectOption('pro');
    await grant.locator('button[type=submit]').click();
    await owner.locator('#toast', { hasText: 'تم منح الخطة' }).waitFor();
    check('owner granted pro to alice (audited)', (await owner.locator('#view').innerText()).includes('billing.admin_grant'));
    await shot(owner, '06-desktop-admin');
    await owner.goto(`${BASE}/#plans`);
    await owner.locator('h1', { hasText: 'الاشتراكات' }).waitFor();
    await shot(owner, '07-desktop-plans');

    const alice = await (await browser.newContext({ viewport: { width: 1366, height: 900 }, locale: 'ar' })).newPage();
    alice.on('pageerror', (e) => consoleErrors.push(String(e)));
    await alice.goto(`${BASE}/#login`);
    const login = alice.locator('form', { hasText: 'تسجيل الدخول' });
    await login.locator('input[name=email]').fill('alice@example.test');
    await login.locator('input[name=password]').fill(PASSWORD);
    await login.locator('button[type=submit]').click();
    await alice.locator('#who', { hasText: 'بحث برو' }).waitFor();
    check('header shows no stray "null"', !(await alice.locator('#who').innerText()).includes('null'));
    await alice.goto(`${BASE}/#lab`);
    await alice.locator('h2', { hasText: 'إعداد الاختبار' }).waitFor();
    await alice.locator('select[name=strategy]').selectOption('breakout');
    await alice.locator('button', { hasText: 'شغّل الاختبار' }).click();
    await alice.locator('h3', { hasText: 'خارج العينة' }).waitFor();
    const lab = await alice.locator('#view').innerText();
    check('backtest ran with OOS split and cost sensitivity', lab.includes('حساسية التكاليف') && lab.includes('ليس احتمالًا مستقبليًا'));
    await shot(alice, '08-desktop-backtest');
    await alice.goto(`${BASE}/#dashboard`);
    await alice.locator('h2', { hasText: 'مساحتك الخاصة' }).waitFor();
    await shot(alice, '09-desktop-dashboard');

    // isolation through the real HTTP stack: the owner cannot read alice's watchlist id via the API
    const aliceLists = await alice.evaluate(async () => (await (await fetch('/api/watchlists')).json()).watchlists);
    const wid = aliceLists[0].id;
    const status = await owner.evaluate(async (id) => (await fetch(`/api/watchlists/${id}`)).status, wid);
    check('another account gets 404 for alice\'s watchlist over HTTP', status === 404, `status ${status}`);
    const forged = await owner.evaluate(async (id) => (await fetch(`/api/watchlists/${id}`, { method: 'DELETE' })).status, wid);
    check('request without CSRF token refused', forged === 403, `status ${forged}`);
  } catch (e) {
    check('smoke run completed', false, String(e && e.stack || e));
  } finally {
    await browser.close();
    fs.rmSync(tmpCsv, { force: true });
  }
  check('no page JavaScript errors', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '));
  const failed = checks.filter((c) => !c.ok);
  console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`);
  process.exit(failed.length ? 1 : 0);
})();
