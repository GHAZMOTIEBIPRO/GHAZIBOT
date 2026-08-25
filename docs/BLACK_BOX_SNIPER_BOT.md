# بلاك بوكس × سنايبر

هذا المسار يربط مؤشر **سنايبر** في TradingView مع رادار العقود والأخبار في GHAZIBOT.

## ما الذي يعمل؟

1. TradingView يرسل إشارة سنايبر إلى `POST /webhook/sniper` بصيغة JSON.
2. الخادم يتحقق من الرسالة، يمنع التكرار، ويرسل الإشارة إلى Telegram إذا اجتازت حد الجودة.
3. عامل خلفي يفحص `data/universe.txt` دوريًا، ثم يجمع المحفزات الرسمية/الأخبار، يرتب الأسهم، ويفحص عقود الخيارات.
4. الفرص الجديدة والأخبار الجوهرية ترسل إلى Telegram مع المصدر وجودة البيانات.
5. لا توجد أوامر شراء/بيع تلقائية ولا اتصال مباشر بحساب وساطة.

## متغيرات التشغيل

```env
BLACK_BOX_BOT_ENABLED=true
BLACK_BOX_SCAN_MINUTES=15
BLACK_BOX_TOP_STOCKS=20
BLACK_BOX_TOP_OPTIONS=15
BLACK_BOX_UNIVERSE=data/universe.txt
BLACK_BOX_BOT_STATE=data/live/black_box_bot_state.json
SNIPER_NOTIFY_SCORE=80
SNIPER_WEBHOOK_SECRET=replace-with-a-long-random-value
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

لجودة عقود لحظية حقيقية استخدم مزودًا مرخصًا/مناسبًا مثل Tradier أو Alpaca/OPRA حسب صلاحية الحساب. Yahoo يبقى fallback ولا ينبغي التعامل معه كـ realtime execution feed.

## رابط TradingView

إذا كان عنوان الخدمة مثل:

```text
https://YOUR-SERVICE.example.com
```

يكون Webhook URL:

```text
https://YOUR-SERVICE.example.com/webhook/sniper?secret=YOUR_SECRET
```

TradingView لا يضمن وصول كل webhook، لذلك راقب سجل Alerts في TradingView أيضًا. يجب ألا يحتوي جسم الرسالة على token أو كلمة مرور.

## صيغة رسالة سنايبر

يجب أن ينتج المؤشر JSON بهذا الشكل:

```json
{
  "event": "signal",
  "direction": "call",
  "symbol": "NVDA",
  "time": "2026-08-25T14:35:00Z",
  "timeframe": "5",
  "score": 88,
  "entry": 181.25,
  "stop": 179.80,
  "target1": 183.10,
  "target2": 185.00,
  "target3": 187.20,
  "engine": "انعكاس",
  "reason": "سحب سيولة + استعادة + اندفاع"
}
```

الأحداث المقبولة: `signal`, `call`, `put`, `setup`, `invalidation`, `target`.

## مثال Pine Script v6 لرسالة webhook

يضاف إلى موضع الإشارة النهائية في سنايبر، مع استبدال أسماء المتغيرات بما يقابلها في النسخة الفعلية:

```pine
f_json_num(float x) =>
    na(x) ? "null" : str.tostring(x, format.mintick)

f_sniper_json(string eventName, string direction, int score, float entry, float stop, float t1, float t2, float t3, string engine, string reason) =>
    "{" +
      "\"event\":\"" + eventName + "\"," +
      "\"direction\":\"" + direction + "\"," +
      "\"symbol\":\"" + syminfo.ticker + "\"," +
      "\"time\":\"" + str.format_time(time, "yyyy-MM-dd'T'HH:mm:ssXXX", "UTC") + "\"," +
      "\"timeframe\":\"" + timeframe.period + "\"," +
      "\"score\":" + str.tostring(score) + "," +
      "\"entry\":" + f_json_num(entry) + "," +
      "\"stop\":" + f_json_num(stop) + "," +
      "\"target1\":" + f_json_num(t1) + "," +
      "\"target2\":" + f_json_num(t2) + "," +
      "\"target3\":" + f_json_num(t3) + "," +
      "\"engine\":\"" + engine + "\"," +
      "\"reason\":\"" + reason + "\"}"

if finalCall and barstate.isconfirmed
    alert(f_sniper_json("signal", "call", lastScore, lastEntry, lastStop, lastT1, lastT2, na, lastEngine, "إشارة سنايبر مؤكدة"), alert.freq_once_per_bar_close)

if finalPut and barstate.isconfirmed
    alert(f_sniper_json("signal", "put", lastScore, lastEntry, lastStop, lastT1, lastT2, na, lastEngine, "إشارة سنايبر مؤكدة"), alert.freq_once_per_bar_close)
```

## تشغيل الخدمة

الـ `Procfile` في هذا الفرع يشغل:

```text
web: python bot_server.py
```

المسارات:

- `GET /health` صحة الخدمة وإعداد Telegram وآخر فحص.
- `GET /scan/latest` ملخص آخر دورة رادار.
- `POST /webhook/sniper` استقبال سنايبر.
- `POST /webhook/tradingview` alias لنفس المسار.

## قواعد مهمة

- التنبيه = رصد وتحليل، وليس أمر تداول.
- `Vol/OI` وحده لا يثبت شراء مؤسسيًا.
- لا نخلط بيانات bid من مزود وask من مزود آخر لتصنيع quote غير حقيقي.
- أي مصدر delayed أو indicative يجب أن يظهر بهذه الصفة.
- أحداث سنايبر تتكرر مرة واحدة فقط لكل fingerprint محفوظ في ledger.
- عند إعادة نشر خدمة على filesystem مؤقت، يفضل نقل `BLACK_BOX_BOT_STATE` إلى persistent disk أو مخزن دائم.
