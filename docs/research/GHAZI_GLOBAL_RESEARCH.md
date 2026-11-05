# GHAZI RADAR Ω — بحث المصادر والبرمجيات المفتوحة (2026-11-05)

كل سطر هنا له دليل: رقم تشغيل على GitHub Actions، أو رابط رسمي مع تاريخ القراءة، أو بيانات من GitHub API (الترخيص، النجوم، آخر دفع). لا شيء من الذاكرة. ما لم أصل إليه مذكور صراحة في القسم 6.

## 1. الخلاصة

1. **البوت والموقع يعملان، والمسار الخاص معطّل بسبب إعدادات لا بسبب الكود:**
   - **مفتاحا Alpaca مخزّنان بالعكس.** فحص `settings-check` (التشغيل 41941112955، 2026-11-05 00:24 UTC) أعطى:
     - `alpaca_keys = REJECTED_HTTP_401`؛
     - `alpaca_reversed_order_probe = VALID`؛
     - التشخيص: `SECRETS_SWAPPED_OWNER_MUST_EXCHANGE_THE_TWO_VALUES`.

     أكد ذلك فحص مستقل على الفرع `ccr-alpaca-key-probe` (التشغيل 42005843804): رفض 401 من حسابي paper وlive، ومن الأسعار والـ screener والخيارات.
   - المتغيرات `DATA_TERMS_CONFIRMED` و`ALPACA_PRIVATE_ALERTS_AUTHORIZED` و`TELEGRAM_OWNER_USERNAME` غير مضبوطة. لذلك يتخطى الفحص الخاص (`private-market-scan.yml`) عمله بحالة `BLOCKED_NO_INTERNAL_ENTITLEMENT`، والتسليم الخاص بحالة `PRIVATE_SEND_NOT_AUTHORIZED`.
   - `SEC_USER_AGENT` غير موجود، فمصدر SEC EDGAR في محرك المحفزات `UNAVAILABLE` (تشغيل catalyst 41955543829).
2. **لا يوجد مصدر مجاني يسمح بالنشر العام لأسعار خيارات لحظية قابلة للتنفيذ.**
   - كل المسارات المجانية الحقيقية حسابات وساطة للاستخدام الشخصي.
   - البديل الآخر تغذية «Indicative» مشتقة ومؤخرة.
   - النشر العام لأسعار OPRA يتطلب ترخيص توزيع مدفوعًا.
3. **أفضل مسار لأسعار تنفيذية بلا اشتراك بيانات: tastytrade API لصاحب حساب مموّل.**
   - رمز التحديث لا تنتهي صلاحيته، فالتشغيل الآلي غير المراقَب ممكن.
   - الاستخدام: خاص فقط، أي رسائل للمالك في محادثته الخاصة.
   - بوابة V11 الحالية تشترط مصدرين حيّين مستقلين للموافقة. حساب واحد لا يكفي لحالة CONFIRMED.
   - لن أخفف هذا الشرط.

## 2. مصادر بيانات الخيارات والأسعار

| المصدر | المجاني | لحظي؟ | التشغيل الآلي | النشر العام | الحكم لهذا المشروع |
|---|---|---|---|---|---|
| **Alpaca Basic** (المفاتيح موجودة) | خيارات «Indicative» + أسهم IEX | الخيارات مشتقة من OPRA، والصفقات متأخرة 15 دقيقة | API رسمي | ممنوع (`telegram_sharing` و`public_display_raw` = RESTRICTED في `data/source_rights.json`) | **يعمل فورًا بعد تبديل المفتاحين**: بحث خاص + تنبيهات للمالك. ليس تنفيذيًا |
| Alpaca Algo Trader Plus | لا | OPRA | API رسمي | ممنوع | ترقية مدفوعة؛ الصفحة الرسمية تذكر 99$ شهريًا للخطة |
| **tastytrade API** | مع حساب **مموّل** | REST لحظي فيه `updated-at`؛ DXLink للبث | OAuth؛ رمز التحديث «لا ينتهي» | ممنوع (حساب شخصي) | **أفضل مسار تنفيذي بلا اشتراك**. يتطلب فتح حساب وتمويله، ثم محوّل جديد (القسم 5) |
| Schwab Trader API | مع حساب | لحظي + سلاسل وبث | رمز التحديث ينتهي بعد 7 أيام ويتطلب دخولًا يدويًا | ممنوع | غير مناسب للتشغيل غير المراقَب |
| Tradier | Sandbox مجاني | Sandbox متأخر؛ الإنتاج لحساب الوساطة | API رسمي (المحوّل موجود في الكود) | ممنوع | مصدر حيّ ثانٍ محتمل مع tastytrade لإكمال نصاب V11 |
| MarketData.app | 100 طلب يوميًا | البيانات المجانية متأخرة 24 ساعة على الأقل | API | غير موضح | بحث تاريخي فقط |
| Massive (Polygon) Options Basic | نهاية اليوم، 5 طلبات/دقيقة | لا | API | حسب الخطة | تحقق نهاية اليوم فقط |
| ThetaData | شريحة مجانية محدودة | — | تطبيق محلي | — | الخطط المدفوعة من 40$ |
| ORATS / Intrinio / FlashAlpha | لا أو محدود جدًا | — | API | — | مدفوعة |
| Cboe delayed، Yahoo، Nasdaq.com | — | — | ممنوع بالشروط | ممنوع | **مغلقة بقرار قائم** (CLAUDE.md) |
| OCC (حجم وOI يومي) | نعم | لا (يومي) | بشرط المتغير `OCC_MARKET_DATA_AUTOMATION_APPROVED` | — | سياق فقط؛ مطفأ حاليًا |
| SEC EDGAR، openFDA، Federal Register، USAspending، ClinicalTrials، Treasury، CFTC | نعم | حسب النشر | رسمي | ملكية عامة أو بشروط إسناد | **مستخدمة**؛ SEC يحتاج `SEC_USER_AGENT` |

## 3. مشاريع GitHub مفتوحة المصدر (من GitHub API، 2026-11-05)

قاعدة المستودع (AGENTS.md): MIT/BSD/Apache قابلة للدمج؛ GPL/AGPL لا تدخل النواة؛ الترخيص غير الواضح = لا نسخ.

| المشروع | الترخيص | ⭐ | آخر دفع | الوظيفة | الحكم |
|---|---|---|---|---|---|
| tradingview/lightweight-charts | Apache-2.0 | 17766 | 2026-11-05 | شارت مالي | **مستخدم** (صفحة التوصية) |
| tastyware/tastytrade | MIT | 259 | 2026-08-07 | SDK غير رسمي لـ tastytrade (REST + DXLink) | **مرجع للمحوّل**؛ منه أُخذت أشكال الحقول |
| tastytrade/tastytrade-api-js | MIT | 107 | 2026-05-17 | SDK رسمي JS | مرجع |
| dxFeed/dxLink | MPL-2.0 | 19 | 2026-11-04 | بروتوكول البث | مرجع بروتوكول؛ لا نسخ |
| dgunning/edgartools | MIT | 2836 | 2026-11-05 | قراءة SEC | مُقيَّم سابقًا (`edgartools_research_adapter.py`) |
| joshyattridge/smart-money-concepts | MIT | 2144 | 2026-04-03 | SMC بايثون | مرجع لعوامل البنية |
| marketcalls/opengreeks | MIT | 27 | 2026-05-31 | Greeks وIV | مرشح للتحقق المتقاطع من Greeks |
| simonro/Edge-GEX-Lab | MIT | 60 | 2026-11-03 | خريطة GEX محلية | مرجع منهجي |
| zrack/gex-terminal | MIT | 27 | 2026-10-20 | GEX وإعادة تشغيل | مرجع منهجي |
| gammagrid/gammagrid | AGPL-3.0 | 93 | 2026-10-12 | لوحة GEX | **لا يدخل النواة**؛ يوجد جسر بحثي (`gammagrid_research.py`) |
| goldspanlabs/optopsy | AGPL-3.0 | 1512 | 2026-11-04 | اختبار خلفي للخيارات | لا يدخل النواة |
| Lumiwealth/lumibot | GPL-3.0 | 2210 | 2026-11-05 | إطار تداول | لا يدخل النواة |
| EazyDuz1t/EzOptions-Schwab | GPL-3.0 | 45 | 2026-10-11 | GEX لـ Schwab | لا يدخل النواة |
| Epistates/rustyschwab، ibouazizi/schwab-trader | Apache-2.0 / MIT | 7 / 15 | 2026 | عملاء Schwab | غير مفيد: قيد السبعة أيام |

**بوتات Telegram العامة:** نتائج البحث عن «telegram options alerts bot» كانت مشاريع صغيرة بلا ترخيص (NONE)، معظمها للكريبتو أو الخيارات الثنائية أو السوق الهندي. لا شيء صالح للنسخ أو الدمج. منطق التنبيه الموجود في المستودع (V11، إزالة التكرار، فصل WATCH عن CONFIRMED، التعديل بدل التكرار) أكثر صرامة مما وجدت.

## 4. المنتديات والمواقع المتخصصة

| المصدر | ما استُخلص |
|---|---|
| [منتدى Alpaca: تغذية Indicative](https://forum.alpaca.markets/t/what-is-the-indicative-pricing-feed-for-options/14595) | موظف Alpaca: التغذية «مشتقة» من OPRA، والعروض «ليست عروض OPRA فعلية»، والصفقات متأخرة 15 دقيقة. يؤكد تصنيفها بحثية في `execution_confidence.py` |
| [وثائق Alpaca للبيانات](https://docs.alpaca.markets/docs/about-market-data-api) | Basic مجاني = Indicative؛ OPRA ضمن Algo Trader Plus |
| [tastytrade OAuth2](https://developer.tastytrade.com/docs/authentication/oauth2/) | رمز التحديث طويل الأجل «لا ينتهي»؛ رمز الوصول 15 دقيقة؛ التطبيق الشخصي مقصور على حساب صاحبه |
| [tastytrade Market Data](https://developer.tastytrade.com/docs/concepts/market-data/) | REST لحظي لأصحاب الحسابات المموّلة؛ لا يوجد مسار REST متأخر؛ حتى 100 رمز في الطلب |
| [LumiBot: Schwab](https://lumibot.lumiwealth.com/brokers.schwab.html) | رمز التحديث ينتهي بعد 7 أيام ويتطلب دخولًا يدويًا |
| [MarketData.app: الحساب المجاني](https://www.marketdata.app/docs/account/free-accounts/) | 100 طلب يوميًا؛ البيانات المجانية متأخرة 24 ساعة على الأقل |
| [مقارنة FlashAlpha 2026](https://flashalpha.com/articles/best-options-data-apis-2026) | لا توجد شريحة مجانية لحظية لدى المزودين المتخصصين. كاتب المقال صاحب أحد المنتجات، فهو مرجع ثانوي |

## 5. المحوّل المقترح لـ tastytrade (تصميم جاهز للتنفيذ عند فتح الحساب)

- **المصادقة:** `POST https://api.tastyworks.com/oauth/token` مع الحقول `grant_type=refresh_token` و`refresh_token` و`client_secret`، وترويسة `User-Agent` إلزامية. ثم `Authorization: Bearer`.
- **السلسلة:** `GET /option-chains/{symbol}/nested`. الشكل: `data.items[].expirations[]`، وفيها `expiration-date` و`settlement-type` و`strikes[]` بالحقول `strike-price` و`call` و`put`. رموز `call` و`put` بصيغة OCC مع مسافات حشو.
- **الأسعار:** `GET /market-data/by-type?equity-option=…` (حتى 100 رمز)، والحقول `bid` و`ask` و`bid-size` و`ask-size` و`last` و`volume` و`open-interest` و`updated-at`.
- **الحوكمة:**
  - نطاق خاص فقط (`GHAZI_PIPELINE_SCOPE=private`، مثل Alpaca).
  - عائلة `tastytrade` تُضاف إلى `public_guard.FAMILY_TOKENS["account_price_apis"]` قبل أي استخدام، حتى لا يُعامل مصدر مجهول كقابل للنشر.
  - وسم المصدر «brokerage account feed» ليقرأه `execution_confidence` كـ ACCOUNT.
- **لماذا لم يُبنَ الآن:** لا يوجد حساب ولا مفاتيح لاختباره، وكود مزود بيانات غير مُختبر على مصدره الحقيقي يخالف مبدأ «تحقق قبل الإنتاج». يُبنى ويُختبر في نفس اليوم الذي يتوفر فيه الحساب.

## 6. ما لم أصل إليه

- **Reddit وX:** لم أقرأ نقاشاتهما مباشرة في هذه الجولة. لم أعتمد على آراء حسابات اجتماعية كدليل، وهذا يطابق شرط المهمة نفسها.
- **صفحة دعم tastytrade عن الحسابات غير الممولة:** لم تُحمّل (محتوى ديناميكي). شرط «حساب مموّل» مأخوذ من صفحة Market Data الرسمية.
- **حدّ أدنى لتمويل tastytrade:** غير موثّق في الصفحات التي قرأتها.

## 7. قائمة إجراءات المالك (مرتبة حسب الأثر)

| # | الإجراء | المكان | الأثر |
|---|---|---|---|
| 1 | **تبديل قيمتي `ALPACA_API_KEY` و`ALPACA_SECRET_KEY`** | Settings ← Secrets ← Actions | يعيد كل مسارات Alpaca (أسعار، VCP، فحص خاص، خيارات Indicative). مثبت بالاختبار العكسي VALID |
| 2 | `DATA_TERMS_CONFIRMED` = `alpaca` (بعد مراجعة شروط Alpaca لخطتك) | Variables | يفتح بوابة المصدر وفحص `private-market-scan` |
| 3 | `ALPACA_PRIVATE_ALERTS_AUTHORIZED` = `true` | Variables | يسمح بتنبيهات Alpaca إلى محادثتك الخاصة فقط |
| 4 | `TELEGRAM_OWNER_USERNAME` = اسم مستخدمك في Telegram بدون @ | Variables | يتحقق أن الوجهة هي أنت. المحادثة الحالية من نوع `private` بالفعل |
| 5 | `SEC_USER_AGENT` = اسم + بريد للتواصل (شرط SEC) | Secrets | يعيد SEC EDGAR لمحرك المحفزات |
| 6 | اختياري: حساب tastytrade مموّل، ثم OAuth client + grant | tastytrade | أسعار لحظية خاصة. المحوّل يُبنى فور توفره |
| 7 | اختياري: مصدر حيّ ثانٍ مستقل (مثل Tradier إنتاجي) | — | مطلوب لنصاب V11 (مصدران) لتصل CONFIRMED |
