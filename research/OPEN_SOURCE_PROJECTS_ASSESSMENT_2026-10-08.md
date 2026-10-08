# تقييم مشاريع مفتوحة المصدر لتطوير BLACK BOX Omega

**التاريخ:** 2026-10-08
**النطاق:** بحث مستقل في 12 مستودعًا؛ لم يُنفّذ اختبار حي أو دمج إنتاجي لأي مشروع في مرحلة البحث.

## منهج القرار

تمت مراجعة صفحات GitHub الرسمية وREADME وLICENSE وملفات الإعداد/التوثيق حيث أمكن. تم فصل **ترخيص الكود** عن **ترخيص بيانات السوق**، وعدم اعتبار yfinance وYahooquery وOpenBB/Yahoo مصادر مستقلة؛ كلها تصل في هذه المسارات إلى عائلة Yahoo. أي نتيجة مستقبلية تبقى shadow حتى تمر عبر provenance وfreshness وschema وV11.

## المقارنة التنفيذية

| المشروع | الترخيص/الصيانة | مصدر البيانات الفعلي | القرار | الفائدة المحتملة |
|---|---|---|---|---|
| [yfinance](https://github.com/ranaroussi/yfinance) | Apache-2.0؛ نشط، دون SLA | Yahoo Finance غير الرسمي؛ حدود/شروط Yahoo منفصلة | SHADOW_VALIDATION | أسعار/تاريخ وfundamentals كمرجع shadow، لا إنتاج |
| [yahooquery](https://github.com/dpguthrie/yahooquery) | MIT؛ إصدار/نشاط أقدم نسبيًا | Yahoo Finance؛ premium اختياري لا يضيف استقلالية | SHADOW_VALIDATION | بديل نقل فقط عند فشل transport، لا مصدر ثانٍ |
| [pandas-ta](https://github.com/twopirllc/pandas-ta) | LICENSE/المستودع الرسمي غير قابل للتحقق في الفحص؛ PyPI Beta | لا يجلب بيانات؛ يحسب على OHLCV مدخل | RESEARCH_ONLY | لا يدخل قبل حسم provenance والترخيص |
| [TA-Lib Python](https://github.com/TA-Lib/ta-lib-python) | BSD-2-Clause؛ نشط، v0.8.1 | لا يجلب بيانات؛ حساب محلي native C | SHADOW_VALIDATION | مرجع مستقل لمؤشرات RSI/ATR/SMA/MACD |
| [vectorbt](https://github.com/polakowo/vectorbt) | Apache-2.0 + Commons Clause؛ نشط | ملفات/مزودات المستهلك، وYFData عبر Yahoo | SHADOW_VALIDATION | backtest متجهي على fixtures مرخصة؛ ليس core تجاريًا قبل مراجعة |
| [backtrader](https://github.com/mementum/backtrader) | GPLv3؛ آخر نشاط الأساسي قديم | ملفات محلية أو Yahoo feed قديم | CONCEPTS_ONLY | أفكار backtest فقط؛ لا GPL داخل core |
| [QuantConnect LEAN](https://github.com/QuantConnect/Lean) | Apache-2.0؛ نشط | ملفات محلية أو مزودات/بروكرات متعددة، وليست مجانية موحدة | SHADOW_VALIDATION | replay معزول؛ يمنع brokerage/order |
| [Freqtrade](https://github.com/freqtrade/freqtrade) | GPLv3؛ نشط جدًا | CCXT وبورصات crypto؛ ليس مصدر أسهم أمريكية | CONCEPTS_ONLY | أفكار data download/rate limit فقط |
| [CCXT](https://github.com/ccxt/ccxt) | MIT؛ نشط جدًا | REST/WebSocket للبورصات، crypto أساسًا | SHADOW_VALIDATION | دراسة adapter/capability/rate-limit، لا مصدر options أمريكي |
| [sec-edgar-downloader](https://github.com/jadchaar/sec-edgar-downloader) | MIT؛ نشط؛ تعارض release/CHANGELOG يحتاج تثبيت نسخة | SEC EDGAR الرسمي فقط، 10 req/s وسياسة User-Agent | SHADOW_VALIDATION | جسر قراءة محدود مع provenance، لا قرار مباشر |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | تعارض Apache محلي/AGPL في المصدر الحالي؛ إعادة تسمية/مالك محتمل | connectors؛ Yahoo امتداد غير رسمي، وليس مصدرًا جديدًا | RESEARCH_ONLY | دراسة abstraction فقط حتى حسم الرخصة |
| [GammaGrid](https://github.com/gammagrid/gammagrid) | AGPL-3.0؛ نشط pre-1.0 | Yahoo chains؛ Cboe directory للرموز لا الأسعار | SHADOW_VALIDATION | أفكار GEX/replay فقط، لا اعتماد حي |

## أولويات التنفيذ

1. **TA-Lib shadow adapter** في `requirements-research.txt` فقط: مدخل canonical OHLCV، نسخة مثبتة، no network، لا يغير قرارًا، ويقارن مؤشرات محددة مع التنفيذ الحالي.
2. **SEC read-only adapter** لاحقًا: طلب filing واحد محدود، provenance CIK/accession/hash، allowlist sec.gov، rate cap، وfail-closed؛ لا يستبدل مسار SEC الحالي قبل مقارنة فعلية.
3. **Backtest/replay concepts** من vectorbt/LEAN/backtrader فقط على fixtures محلية مرخصة، دون إدخال GPL/Commons Clause إلى core.
4. **لا تكامل إنتاجي لمزود options**: كل الأدلة تؤكد أن Yahoo/YFinance مصدر بحثي واحد، ولا entitlement حي موثق في البيئة الحالية.

## اختبارات عملية لم تُنفذ بعد

- TA-Lib: OHLCV اصطناعي ثابت، RSI/SMA/ATR/MACD، مقارنة oracle Python، NaN/lookback، input malformed، وعدم الاتصال بالشبكة.
- SEC downloader: filing واحد لـ AAPL في tempdir، User-Agent معلن، التحقق من CIK/form/accession/SHA-256، ومحاكاة 403/timeout.
- Replay: fixture محلي مع gaps/duplicates/timezone، منع look-ahead، ومقارنة baseline.

هذه اختبارات مقترحة وليست ادعاء نجاح. أي اعتماد إنتاجي يتطلب المسار: CODED → TESTED → CI GREEN → MERGED → RUNTIME VERIFIED → EMPIRICALLY VALIDATED.

## المصادر المرجعية

- https://github.com/ranaroussi/yfinance
- https://github.com/dpguthrie/yahooquery
- https://github.com/twopirllc/pandas-ta
- https://github.com/TA-Lib/ta-lib-python
- https://github.com/polakowo/vectorbt
- https://github.com/mementum/backtrader
- https://github.com/QuantConnect/Lean
- https://github.com/freqtrade/freqtrade
- https://github.com/ccxt/ccxt
- https://github.com/jadchaar/sec-edgar-downloader
- https://github.com/OpenBB-finance/OpenBB
- https://github.com/gammagrid/gammagrid
- https://www.sec.gov/os/accessing-edgar-data
