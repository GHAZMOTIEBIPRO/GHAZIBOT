# GHAZIMOTIEB | OPENING FIB Ω — Research only
هذه نسخة من ملفات الحزمة البحثية الأصلية بعد إصلاحات محدودة. **لم تُفعّل في غازي رادار أو Telegram أو أي وسيط**.

## الملفات
- `orb_research_lab.py`: مختبر مستقل على شموع SPY/QQQ وأسهم أمريكية بدقة 5 دقائق، في حال امتلاك المستخدم حق الاستعمال، 6 نماذج × 5 نوافذ × 3 عائلات مستويات.
- `GHAZIMOTIEB_OPENING_FIB_Omega_indicator.pine`: المؤشر العربي المرئي.
- `GHAZIMOTIEB_OPENING_FIB_Omega_strategy.pine`: محاكاة سهم/ETF، لا محاكاة عقد خيارات.
- `../../tests/test_opening_fib_research.py`: اختبارات صناعية لسلامة شروط النطاق والوقت والوقف.

## خطوات التشغيل المحلي
```bash
pip install pandas numpy exchange-calendars pytest
pytest -q tests/test_opening_fib_research.py
python research/opening_fib_omega/orb_research_lab.py --csv /PRIVATE_PATH/licensed_5min.csv --output /PRIVATE_PATH/results.json --cost-bps 12 --symbols SPY QQQ
```

الأعمدة: `symbol,timestamp,open,high,low,close,volume`؛ أوقات الشموع تبدأ الفترة وبها لاحقة Z أو offset؛ لكل جلسة شموع منتظمة كاملة ولا يختلق المختبر شموعًا مفقودة.

## الوضع الحالي
- ملفات Pine **لم تُجمّع في محرر TradingView الرسمي**، ولا نؤكد خلوها من أخطاء الترجمة.
- اختبار JavaScript المستقل ببيانات Alpaca SIP لعام 2026 أنتج نتائج سلبية للمحاكاة الأساسية، لكنه **ليس** تشغيلًا مطابقًا للمختبر Python المعدل.
- لا بيانات خيارات، لا ربحية 0DTE ولا سيولة تنفيذ مثبتة، ولا تداول آلي.
- نتائج عينة الاختبار النهائي محفوظة خارج الاختيار/التطوير ولا تنشر قبل التجميد والتحقق.
- لم تُضف أي بيانات خام أو مفاتيح سوق إلى المستودع. لا تغييرات لمسارات التنفيذ أو التنبيهات الإنتاجية.

اقرأ [تقرير التدقيق الأول](../GHAZIMOTIEB_OPENING_FIB_SIP_AUDIT_20261115.md).
