# حل ربط Telegram بفيبوناتشي غازي — للمستخدم

**ثلاثة مفاتيح للباب:** رقم محادثتك، اختبار وصول رسالة بلا بيانات سوق، وموافقة صاحب حساب Alpaca على استخدام البيانات الخاصة وفق شروط اشتراكه.

## 1. اجلب رقم المحادثة من البوت نفسه، دون مشاركة مفتاحه
1. افتح البوت الخاص بك في Telegram واضغط Start. أرسل رسالة حرفيًا: \`/ghazi_id\`.
2. افتح https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/actions/workflows/opening-fib-daily.yml، اضغط **Run workflow**، فعّل **owner_id_help=true**، واضغط Run workflow.
3. ستصلك رسالة **داخل محادثتك الخاصة** فيها رقم المحادثة. انسخ الرقم فقط. هذا المسار لا يرسل أسعارًا أو بيانات Alpaca.
4. افتح https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/settings/secrets/actions، اختر **New repository secret**:
   - Name: \`TELEGRAM_OWNER_CHAT_ID\`
   - Secret: الرقم الذي أرسله لك البوت
5. إذا ظهر \`OWNER_ID_COMMAND_NOT_FOUND\`، أعد إرسال \`/ghazi_id\` وشغّل المسار فورًا. قد يكون البوت يستهلك الرسائل من getUpdates أو لديه webhook؛ إذا ظهر \`OWNER_ID_WEBHOOK_ACTIVE\`، استخدم وسيلة موثوقة لمعرفة رقم Telegram الخاص بك وأضفه في Secret دون تغيير webhook. لا ترسل Telegram Bot Token في المحادثات أو الصور.

## 2. اختبر وصول Telegram منفصلًا عن بيانات السوق
1. من صفحة GitHub Actions نفسها اضغط **Run workflow**.
2. فعّل \`test_telegram=true\` فقط (واترك باقي خيارات الاختبار false / dry_run true).
3. ابحث في Logs عن \`TELEGRAM_TEST_DELIVERED\` وتحقق من وصول رسالة "غازي رادار | اختبار اتصال ناجح" إلى محادثتك.

هذا الاختبار لا يحتاج ترخيص Alpaca لأنه لا ينقل أي سعر؛ ولا يغير علامة آخر إرسال. إذا ظهر \`TELEGRAM_TEST_OWNER_CHAT_NOT_SET\`، راجع Secret، وإذا ظهر \`TELEGRAM_TEST_BOT_TOKEN_MISSING\` فراجع Secret \`TELEGRAM_BOT_TOKEN\`.

## 3. أذن بإرسال تقرير الحساب **فقط إذا سمحت اتفاقية Alpaca لديك**
- اقرأ شروط حسابك وبيانات السوق. الاستعمال الشخصي على محادثة خاصة ليس نشرًا عامًا، لكنه لا يغني عن الالتزام باتفاقية المصدر والبورصات.
- افتح https://github.com/GHAZMOTIEBIPRO/GHAZIBOT/settings/variables/actions، أنشئ / عدّل Repository variable:
  - Name: \`ALPACA_PRIVATE_ALERTS_AUTHORIZED\`
  - Value: \`true\`
- هذا متغير **إقرار منك** بعد المراجعة، وليس مفتاح Alpaca جديدًا وليس شهادة موافقة رسمية من مزود البيانات؛ **لا تضع true إذا لم تكن شروط استخدامك تسمح بذلك**.
- المتغير \`ALPACA_INTERNAL_DATA_USE_AUTHORIZED\` موجود ومتاح وفق سجل فحص 14 نوفمبر 2026؛ لا تغيّره دون سبب.

## 4. تحقق من الجاهزية
من صفحة workflow اختر **Run workflow** مع \`preflight=true\` فقط. عند ظهور \`PREFLIGHT_READY\` يكون التحقق من مصدر SIP التاريخي، ووجهة Telegram الخاصة، وحقوق الاستخدام اكتمل. هذه ليست رسالة فعلية. بعدها أول تشغيل في جلسة تداول سيرسل التقرير، بشرط ألا تكون هناك أخطاء جديدة أو تأخر جدولة.

**دليل حاسم:** حالة \`DELIVERED\` في تشغيل *schedule* وظهور الرسالة في محادثتك. لا تشارك بوت توكن أو API Keys أو chat ID خارج إعدادات GitHub الخاصة.
