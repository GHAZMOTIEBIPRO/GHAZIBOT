# GHAZI Options Radar

مشروع لفحص عقود الخيارات الأمريكية وترتيب أفضل العقود المرشحة للشراء وفق
السيولة، `Vol/OI`، جودة السعر، Greeks، خطر IV، الاتجاه الفني وحالة السوق.
يدعم تنبيه `NEW_INDEPENDENT_SETUP` مع منع تكرار العقد عبر SQLite.

> البيانات المجانية لا تثبت Smart Money Sweep حقيقيًا لحظيًا. النظام يعرض
> المصدر وحداثته مع كل عقد ويستخدم `aggressor_proxy` بدل ادعاء Sweep مؤكد.

## المزايا

- مزود تلقائي: Tradier ثم MarketData.app ثم Yahoo/yfinance.
- إثراء اختياري من Alpaca للـbid/ask وGreeks.
- فلترة DTE والسيولة والـspread والدلتا وIV مقابل realized volatility.
- EMA 9/21/50/200 وRSI وMACD وATR والحجم النسبي واختراق 20 يومًا.
- تصنيف `A+` إلى `D` ودرجة من 100.
- دخول Limit، هدفان، وقف للعقد ومستوى إبطال على الأصل.
- Telegram/Discord باستخدام Secrets فقط.
- Streamlit وCLI وGitHub Actions كل 15 دقيقة.

## أوزان الدرجة

| المحور | الوزن |
|---|---:|
| السيولة | 25 |
| Vol/OI وaggressor proxy | 25 |
| Delta/Gamma | 15 |
| IV مقابل realized volatility | 15 |
| المحفز الفني | 20 |
| توافق السوق | +2 |
| خصم ضعف المصدر | حتى -10 |

التنبيه المستقل يتطلب افتراضيًا: `Vol/OI >= 2.0`، اختراق/كسر فني بحجم نسبي،
درجة `>= 76`، تنفيذ ليس عند bid، وعقد لم يُنبه عنه سابقًا.

## التشغيل

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python main.py --symbols SPY QQQ NVDA TSLA --top 25
```

لوحة التحكم:

```bash
streamlit run app.py
```

## المصادر

في `.env` استخدم `OPTIONS_PROVIDER=auto`. الأولوية: Tradier، ثم MarketData.app،
ثم Yahoo/yfinance بلا مفتاح. Alpaca يثري السلسلة ولا يستبدل volume/OI.
راجع [تدقيق المصادر](docs/DATA_SOURCES.md).

## التنبيهات

ضع القيم في `.env` محليًا أو GitHub Repository Secrets:

```dotenv
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DISCORD_WEBHOOK_URL=...
```

ثم:

```bash
python main.py --send-alerts
```

لا تضع المفاتيح داخل الكود. إذا ظهر مفتاح في Git history فألغِه وأصدر مفتاحًا
جديدًا؛ حذف السطر لا يلغي المفتاح المكشوف.

## الحدود

- Open Interest لا يتحدث لحظيًا عادةً؛ Vol/OI إشارة لا إثبات.
- snapshot قريب من ask لا يساوي Sweep مؤكدًا.
- Greeks المحلية تقريب Black–Scholes عند غيابها من المزود.
- GitHub Actions قد يتأخر، وليس بنية منخفضة الكمون.
- المشروع لا ينفذ أوامر تداول ولا يضمن الربح.
