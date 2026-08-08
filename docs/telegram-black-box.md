# BLACK BOX Ω — ربط تيليجرام

الربط معمول كذا:

`GHAZIBOT Ω -> فلتر Pre-Explosion -> Telegram`

## السر المطلوب

في GitHub افتح:

`Settings -> Secrets and variables -> Actions -> New repository secret`

وحط:

- الاسم: `TELEGRAM_BOT_TOKEN`
- القيمة: توكن البوت من BotFather

لا تحط التوكن داخل ملف بالكود.

`TELEGRAM_CHAT_ID` اختياري. إذا تركته فاضي، النظام يقرأ آخر رسالة مرسلة للبوت عن طريق `getUpdates` ويطلع Chat ID بنفسه.

## قبل أول تشغيل

أرسل للبوت `/start` أو أي رسالة عادية.

بعدها شغّل Workflow:

`BLACK BOX Omega Telegram Alerts`

أول رسالة بتوصلك:

`BLACK BOX Ω CONNECTED`

بعدها النظام ما يرسل إلا المرشحين اللي يمرون الفلتر.

## الفلتر الافتراضي

- اتجاه صاعد فقط
- Tier = A أو A+
- Explosion Rank >= 80
- Earlyness >= 75
- Dilution Risk < 60
- Risk Penalty <= 38
- البيانات Fresh
- ما يكون السهم Too Late / Extended
- بحد أقصى 3 تنبيهات في التشغيل الواحد

## منع الإزعاج

النظام يحفظ حالة آخر التنبيهات في:

`data/live/telegram_alert_state.json`

وما يعيد نفس التنبيه إلا إذا تغيرت الحالة بشكل واضح، مثل ارتفاع Explosion Rank أو تغير الـTrigger/المحفز.

## ملاحظة

درجة `Pre-Explosion` هنا ترتيب داخلي، مو احتمال رياضي مضمون للحركة.
