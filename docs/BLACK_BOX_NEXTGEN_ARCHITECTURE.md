# BLACK BOX Omega — Next-Gen Architecture

## الهدف

طبقة Black Box فوق الأنظمة الموجودة بدل إعادة كتابة المشروع. تجمع أدلة مستقلة من الشارت، الأخبار والمحفزات، Explosion Radar، الخيارات، التدفق اللحظي، ونتائج replay/calibration.

المبدأ: دمج الأدلة وليس جمع درجات قديمة بشكل أعمى. المصدر المفقود أو الضعيف يخفض جودة الحالة ولا يتحول إلى قيمة مصطنعة.

## مشاريع GitHub التي سنستفيد منها

- OpenBB: توحيد مصادر equities/options/news/macro وواجهات Python/REST/MCP. سنجعله adapter اختياري وليس اعتماداً إجبارياً حتى لا يبطئ المسار الأساسي. urlOpenBBhttps://github.com/OpenBB-finance/OpenBB
- yfinance: fallback للبحث والتاريخ وoption chain، ويدعم WebSocket وAsyncWebSocket. يبقى fallback وليس إثباتاً لبيانات OPRA أو institutional flow. urlyfinancehttps://github.com/ranaroussi/yfinance
- TA-Lib: مؤشرات وcandlestick recognition كميزات للشارت، لا كحكم منفرد. urlTA-Lib Pythonhttps://github.com/TA-Lib/ta-lib-python
- Polars: مسار اختياري لمعالجة scans الكبيرة بعد قياس bottleneck، بدلاً من تبديل Pandas بالكامل. urlPolarshttps://github.com/pola-rs/polars
- QuantConnect LEAN: مرجع event-driven وoptions data/replay architecture، وليس محرك تنفيذ داخل GHAZIBOT. urlLEANhttps://github.com/QuantConnect/Lean
- NautilusTrader: مرجع streaming/event-bus عالي الأداء إذا احتجنا لاحقاً خدمة sub-minute خارج GitHub Actions. urlNautilusTraderhttps://github.com/nautechsystems/nautilus_trader
- Trading Signal Scanner: فكرة دمج options flow + SEC insider + momentum + sentiment + outcome tracking. urlTrading Signal Scannerhttps://github.com/samir-shah-ahmed/trading-signal-scanner
- Unusual Options Scanner: volume/OI + short-window burst + مقارنة حركة العقد بالسهم. سنستفيد من الفكرة مع بوابات جودة بيانات GHAZI. urlUnusual Options Scannerhttps://github.com/Joevue123/unusual-options-scanner
- Squeeze Radar: تقاطع social velocity + short interest + options activity + price confirmation كطبقة اكتشاف مبكر، مع عدم اعتباره دليلاً مؤسسياً. urlSqueeze Radarhttps://github.com/diamondbuild/equity-scanner

## الطبقات

FAST DATA FABRIC
→ NORMALIZATION / FRESHNESS
→ CHART ENGINE
→ NEWS / CATALYST
→ EXPLOSION ENGINE
→ OPTIONS / FLOW
→ MULTI-EVIDENCE FUSION
→ CONTRACT SELECTOR
→ OUTCOME / CALIBRATION
→ ARABIC ALERT + DASHBOARD

## السرعة

- Fast Explosion Radar: 5 دقائق.
- Options Contract Radar: 15 دقيقة.
- عند ظهور candidate قوي، enrich المرشحين فقط بدلاً من إعادة فحص الكون كله.
- cache + single-flight + provider health لمنع تكرار طلبات البيانات.
- WebSocket/streaming يستخدم فقط عندما يكون المصدر فعلاً realtime.
- GitHub Actions ليس بديلاً عن streaming بالثواني؛ GitHub يحدد أقصر schedule دوري بـ5 دقائق. 

## منطق المرشح

لا توجد توصية قوية بسبب عامل واحد. المرشح يرتفع عندما تتفق فئات مستقلة مثل:

Chart + Catalyst + Explosion + Options/Flow

ثم يتم اختيار العقد بعد تحديد اتجاه السهم، مع إبقاء DTE وliquidity وspread وfreshness وOCC gates.

الحالات:
- WATCH: أدلة غير كافية أو متعارضة.
- RESEARCH_CANDIDATE: فئتان مستقلتان أو أكثر مع edge اتجاهي كافٍ.
- CONTRACT_CANDIDATE: بعد اجتياز بوابات العقد.
- EXTENDED: الحركة موجودة لكن لا تتم مطاردة السعر.

كل score هنا evidence score وليس احتمال ربح.

## ما لن نفعله

- لا ندعي sweep أو institutional buying من volume/OI وحدهما.
- لا نحول Yahoo/yfinance إلى OPRA.
- لا نخلط delayed quotes مع realtime.
- لا نغير historical outcomes لتجميل النتائج.
- لا نضيف automated order execution.
- لا نجعل ML/LLM يتجاوز بوابات جودة البيانات.

## التنفيذ التالي

1. ربط fusion بالـpayloads الحالية.
2. إضافة contract-selection gate بعد fusion.
3. إضافة replay/OOS scorecard لكل setup.
4. enrichment انتقائي للـtop candidates.
5. قياس زمن كل provider وcache hit-rate.
6. إدخال Polars اختيارياً في hot paths التي يثبت قياسها أنها عنق زجاجة.
7. إضافة OpenBB adapter اختياري مع provenance لكل نتيجة.
