'use strict';
// Unit checks for public/signal.js pure helpers (no browser needed).
const assert = require('assert');
const path = require('path');
const page = require(path.join(__dirname, '..', 'public', 'signal.js'));

const loc = (pathname, search = '') => ({ pathname, search });
assert.strictEqual(page.signalIdFrom(loc('/options/signal/0123456789abcdef')), '0123456789abcdef');
assert.strictEqual(page.signalIdFrom(loc('/signal', '?id=0123456789abcdef')), '0123456789abcdef');
assert.strictEqual(page.signalIdFrom(loc('/options/signal/<script>')), '');
assert.strictEqual(page.signalIdFrom(loc('/options/signal/0123')), '');

const series = [
  { t: '2026-11-04T15:00:20Z', bid: 0.8, ask: 1.0 },
  { t: '2026-11-04T15:00:05Z', bid: 1.0, ask: 1.2 },
  { t: '2026-11-04T15:00:40Z', bid: 1.2, ask: 1.4 },
  { t: '2026-11-04T15:01:10Z', bid: 1.5, ask: 1.7 },
  { t: 'bad', bid: 9, ask: 9.1 },
  { t: '2026-11-04T15:01:30Z', bid: 0, ask: 1.0 },
  { t: '2026-11-04T15:01:31Z', bid: 2.0, ask: 1.0 },
];
const candles = page.buildCandles(series, 60);
assert.strictEqual(candles.length, 2);
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} != ${b}`);
assert.strictEqual(candles[0].time, Date.parse('2026-11-04T15:00:00Z') / 1000);
near(candles[0].open, 1.1); near(candles[0].high, 1.3); near(candles[0].low, 0.9); near(candles[0].close, 1.3);
assert.strictEqual(candles[0].quotes, 3);
assert.strictEqual(candles[1].quotes, 1);
assert.deepStrictEqual(page.buildCandles(null, 60), []);

assert.strictEqual(page.pricesBlocked({ display: { prices: 'LICENSE_BLOCKED' }, levels: { status: 'LICENSE_BLOCKED' } }), true);
assert.strictEqual(page.pricesBlocked({ display: { prices: 'PERMITTED' }, levels: { stop: 1 } }), false);
assert.strictEqual(page.pricesBlocked(null), true);
assert.strictEqual(page.reasonAr('bid_reached_t1'), 'سعر العرض بلغ الهدف الأول');
assert.strictEqual(page.reasonAr('data_stale:stale'), 'توقف البيانات أو تسعيرة غير قابلة للتنفيذ');
assert.ok(!/[a-z_]{4,}/.test(page.reasonAr('some_new_code')), 'unknown codes must not leak English');
console.log('signal page checks passed');
