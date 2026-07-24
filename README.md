# GHAZI Stocks & Options Radar

مشروع بحث ورقي مجاني يجمع **المحفزات الرسمية + ترتيب الأسهم + اختيار عقود الخيارات + قياس النتائج**.
يبدأ من SEC وFDA، ثم يحلل السهم فنيًا وقطاعيًا، ويفحص العقود للأسهم الأعلى تقييمًا، ويحفظ الأدلة داخل GitHub.

> البيانات المجانية لا تثبت Smart Money Sweep لحظيًا ولا تضمن الربح. النظام يعرض جودة المصدر وحداثته، ولا ينفذ أوامر تداول.

## طريقة التشغيل المعتمدة

المشروع **Dashboard Only**:

- يعرض النتائج في صفحة الويب.
- يحفظ الإشارات والنتائج والمعايرة داخل GitHub.
- لا يرسل بريدًا أو Telegram أو Discord.
- لا ينفذ أوامر تداول آلية.
- لا يغير أوزان النموذج قبل اكتمال عينة ناضجة.

## المزايا

- الأسهم المرشحة مع CALL/PUT والدخول والأهداف والإبطال.
- أفضل العقود مع DTE وVol/OI وIV وDelta والسبريد والسيولة.
- محفزات SEC وopenFDA مع المصدر والثقة والقيمة وغرض الإفصاح.
- تحليل Form 4 وSchedule 13D ومخاطر S-1 وS-3 و424B5 وATM.
- EMA 9/21/50/200 وRSI وMACD وATR والحجم النسبي والقوة القطاعية.
- رفض العقود المعدلة وغير القياسية والبيانات القديمة والسبريد الواسع.
- عرض الفرص المرفوضة وسبب الرفض.
- سجل MFE وMAE ونقاط 30m و60m و1d و3d و5d و10d.
- قياس ترتيب الهدف والوقف بشموع 5 دقائق؛ اللمس داخل الشمعة نفسها يسجل `ambiguous_same_bar` ولا يحتسب فوزًا.
- محرك بيانات هجين يعزل فشل كل مزود ويعود تلقائيًا إلى مصدر احتياطي.

## المصادر

### تعمل دون مفاتيح خاصة

1. SEC EDGAR — إفصاحات رسمية.
2. openFDA / Drugs@FDA — يعمل ضمن الحد العام دون مفتاح.
3. Nasdaq Market Movers — لاكتشاف الرموز المتحركة، مع تصفية warrants/rights/units.
4. Yahoo/yfinance — احتياط بحثي غير رسمي للأسعار والعقود.

### مصادر حساب مجاني اختيارية

- Tradier: سلاسل خيارات وبيانات أسهم حسب صلاحيات الحساب؛ Sandbox متأخر ولا يوفر Greeks.
- Alpaca: إثراء bid/ask وGreeks وبيانات الأسهم عند توفر صلاحية الحساب.
- MarketData.app: مصدر عقود اختياري.
- Twelve Data: شموع أسهم اختيارية ضمن رصيد الخطة.
- Polygon Stocks Basic: شموع وبيانات تاريخية اختيارية ضمن حد الخطة.
- Alpha Vantage: احتياط منخفض الحصة للبيانات اليومية/الزمنية.
- FRED: مفتاح اختياري للتوسع الماكروي لاحقًا.

راجع `docs/FREE_DATA_SOURCE_POLICY.md` قبل إضافة أي مصدر. لا يستخدم المشروع استخراجًا آليًا لجداول Cboe المحظورة.

## محرك البيانات الهجين

### عقود الخيارات

في `OPTIONS_PROVIDER=auto`:

1. يجلب كل مصدر عقود مهيأ: Tradier وMarketData.app.
2. يضيف Yahoo كاحتياط.
3. يدمج الصفوف حسب OCC contract symbol.
4. يعتمد الصف الأعلى جودة ويملأ الحقول الناقصة من المصادر الأخرى.
5. يثري النتائج من Alpaca عند توفره.

### أسعار الأسهم والشموع

```dotenv
DAILY_PRICE_PROVIDER_ORDER=yahoo,tradier,alpaca,twelve_data,polygon,alpha_vantage
INTRADAY_PRICE_PROVIDER_ORDER=tradier,alpaca,twelve_data,polygon,yahoo,alpha_vantage
```

الترتيب اليومي يبدأ من Yahoo لحماية حصص الخطط المجانية الصغيرة عند فحص عشرات الأسهم. التتبع الزمني يفضل المصادر الرسمية المهيأة ثم يعود إلى Yahoo.

## تتبع ترتيب الهدف والوقف

لكل إشارة يحفظ النظام:

- `first_target_1_at`
- `first_target_2_at`
- `first_stop_at`
- `outcome_order`
- `ambiguous_same_bar`
- `bar_resolution`
- `path_source`

النتائج الممكنة:

- `target_1_first`
- `target_2_first`
- `stop_first`
- `ambiguous_same_bar`
- `open`

هذا يقلل تحيز اللقطات النصف ساعية، لكنه لا يحول البيانات المجانية إلى إثبات تنفيذ فعلي للعقد.

## التشغيل المحلي

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # Windows
# cp .env.example .env   # macOS/Linux
python main.py --mode all --top 15
```

## الإعدادات الاختيارية

```dotenv
OPTIONS_PROVIDER=auto
TRADIER_TOKEN=
TRADIER_BASE_URL=https://sandbox.tradier.com
MARKETDATA_TOKEN=
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
ALPACA_STOCK_FEED=iex
TWELVE_DATA_API_KEY=
POLYGON_API_KEY=
ALPHA_VANTAGE_API_KEY=
FRED_API_KEY=
OPENFDA_API_KEY=
SEC_USER_AGENT=GHAZI Options Radar your-email@example.com
```

لا تكتب أي مفتاح داخل الكود أو JSON العام؛ يوضع في GitHub Actions Secrets فقط.

## GitHub Actions

- تشغيل يدوي عبر `workflow_dispatch`.
- لقطة قبل الجلسة.
- تشغيل في الدقيقتين `07` و`37` خلال نافذة السوق.
- حفظ `latest.json` وسجل الإشارات والنتائج وتقرير المعايرة.
- فتح Issue مراجعة مرة واحدة بعد اكتمال 100 إشارة ناضجة.
- لا تعديل تلقائي للأوزان.

## الاختبارات

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check .
```

يشمل CI اختبارات Python، تجميع الملفات، JavaScript، JSON، ومسار target/stop الزمني.

## حدود لا يمكن تجميلها

- Open Interest لا يتحدث لحظيًا عادة؛ Vol/OI إشارة لا إثبات.
- السعر قرب ask لا يثبت Sweep مؤسسيًا.
- Tradier Sandbox متأخر ولا يوفر Greeks.
- الخطط المجانية لها حدود وترخيص استخدام؛ يجب احترام شروط الحساب.
- الشمعة الزمنية لا تحدد ترتيب الأحداث داخل الشمعة نفسها، لذلك تسجل الحالة ملتبسة.
- أسعار العقود المرصودة ليست إثبات fill أو slippage فعلي.
- لا يوجد ضمان ربح أو تنفيذ آلي.
