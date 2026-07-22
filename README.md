# GHAZI Stocks & Options Radar

مشروع مجاني يجمع **المحفزات الرسمية + ترتيب الأسهم + اختيار أفضل عقود الخيارات**.
يبدأ من SEC وFDA والأخبار، ثم يحلل السهم فنيًا، وبعدها يفحص العقود فقط للأسهم
الأعلى تقييمًا.

> البيانات المجانية لا تثبت Smart Money Sweep لحظيًا ولا تضمن الربح. النظام يعرض
> جودة المصدر وحداثته، ويستخدم `aggressor_proxy` بدل ادعاء Sweep مؤكد.

## المزايا

- صفحة للأسهم المرشحة مع الدخول والأهداف والوقف.
- صفحة لأفضل العقود المرتبطة بالأسهم الأعلى تقييمًا.
- صفحة لمحفزات SEC EDGAR وopenFDA والأخبار.
- قراءة 8-K و6-K و13D وForm 4 والكلمات الجوهرية داخل المستندات.
- اكتشاف الطروحات والتخفيف والأخبار السلبية وخصمها من الدرجة.
- تحليل EMA 9/21/50/200 وRSI وMACD وATR والحجم النسبي واختراق 20 يومًا.
- فلترة DTE والسيولة وVol/OI والـspread والدلتا وIV مقابل realized volatility.
- تصنيف من `A+` إلى `D` ودرجة من 100.
- Telegram للتنبيه الفوري وبريد يومي اختياري.
- Streamlit وCLI وGitHub Actions مجدول.
- SQLite لمنع تكرار تنبيه العقد نفسه.

## المصادر المجانية

1. SEC EDGAR: إفصاحات رسمية ولا يحتاج مفتاح API.
2. openFDA / Drugs@FDA: يعمل دون مفتاح ضمن حد يومي، والمفتاح المجاني اختياري.
3. Yahoo/yfinance: أسعار وشارت وسلاسل خيارات وأخبار، مع تنبيه أنه مصدر غير رسمي.
4. Tradier أو MarketData.app أو Alpaca اختيارية فقط عند إضافة مفتاح؛ المشروع لا
   يتوقف بدونها ويعود إلى Yahoo.

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

لوحة التحكم:

```bash
streamlit run app.py
```

## الأقسام داخل الصفحة

1. **الأسهم المرشحة:** درجة السهم، منطقة الدخول، هدفان، وقف، RSI، الحجم النسبي،
   المحفز وسبب الاختيار.
2. **أفضل العقود:** تاريخ الانتهاء، Strike، Call/Put، Vol/OI، IV، Delta، Spread،
   الدخول والأهداف والوقف.
3. **محفزات SEC وFDA:** المصدر الرسمي والرابط والكلمات التي رفعت أو خفضت الدرجة.
4. **الأخطاء والقيود:** أي مصدر فشل أو بيانات لم تتوفر.

## اختيار مصدر العقود

```dotenv
OPTIONS_PROVIDER=auto
```

الأولوية في `auto`:

1. Tradier عند وجود `TRADIER_TOKEN`.
2. MarketData.app عند وجود `MARKETDATA_TOKEN`.
3. Yahoo/yfinance كخيار بلا مفتاح.

Alpaca يثري bid/ask وGreeks عند توفره، ولا يستبدل volume/OI.

## SEC وFDA

SEC يطلب من البرامج تعريف التطبيق ووسيلة تواصل:

```dotenv
SEC_USER_AGENT=GHAZI Options Radar your-email@example.com
```

openFDA يعمل دون مفتاح ضمن الحد المجاني، ويمكن إضافة مفتاح مجاني لرفع الحد:

```dotenv
OPENFDA_API_KEY=
```

## Telegram والبريد

Telegram للتنبيه الفوري:

```dotenv
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

البريد اليومي عبر Gmail SMTP باستخدام App Password:

```dotenv
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
REPORT_EMAIL_TO=
```

التشغيل مع التقرير:

```bash
python main.py --mode all --top 15 --send-alerts --send-report --send-email
```

لا تضع المفاتيح داخل الكود. أي مفتاح ظهر سابقًا في Git history يجب إلغاؤه وإصدار
مفتاح جديد؛ حذف السطر من آخر نسخة لا يلغي المفتاح المكشوف.

## GitHub Actions

الـworkflow يفحص الأسهم والعقود كل 15 دقيقة خلال نافذة السوق، ويرسل تقريرًا يوميًا
قبل الجلسة عند ضبط Secrets. جدولة GitHub Actions قد تتأخر، ولذلك ليست بديلًا عن
بيانات Tick لحظية أو خادم تداول منخفض الكمون.

## منطق التقييم

### السهم

- الاتجاه والمتوسطات وMACD وRSI والحجم والاختراق.
- السيولة بالدولار.
- محفز رسمي إيجابي أو سلبي.
- توافق SPY وQQQ وVIX.
- خصم التشبع والامتداد والطروحات والتخفيف.

### العقد

- Volume وOpen Interest وVol/OI والـspread.
- Delta/Gamma وIV مقارنة بالتذبذب المحقق.
- مطابقة Call/Put مع اتجاه السهم.
- إضافة درجة المحفز الرسمي إلى العقد.
- تنبيه مستقل عند اكتمال السيولة والدرجة والاختراق أو المحفز القوي.

## الاختبارات

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check .
```

## حدود لا يمكن تجميلها

- Open Interest عادة لا يتحدث لحظيًا داخل الجلسة؛ Vol/OI إشارة لا إثبات.
- السعر القريب من ask لا يساوي Sweep مؤكدًا.
- Greeks المحسوبة محليًا تقريب Black–Scholes عند غياب Greeks من المزود.
- أخبار وموافقات FDA قد تحتاج مطابقة اسم الشركة بالرمز، ولذلك يعرض النظام درجة
  ثقة المطابقة ومصدرها.
- لا يوجد ضمان ربح، ولا تنفيذ آلي للأوامر في المشروع.
