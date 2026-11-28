# COMPETITIVE EDGE — خط الأساس قبل التغيير (2026-11-28)

**المرجع:** main عند `68fd13e` (‏#468)، والإصدار الوظيفي `21cf9b9` (‏#467). التطوير في `claude/competitive-edge-omega`.

**تعريف الحالات:**
- CODED: الكود موجود.
- TESTED: اختبارات CI ناجحة.
- MERGED: مدموج في main.
- DEPLOYED: منشور.
- LIVE_VERIFIED: ثبت في جلسة تداول حقيقية.
- EDGE_PROVEN: أفضلية مثبتة ببوابة القسم E.
- نجاح CI لا يعني LIVE_VERIFIED. **لا محرك LIVE_VERIFIED ولا EDGE_PROVEN حتى الآن.**

| المحرك | الملفات | workflow | المصدر وحقوقه | زمن البيانات | التغطية | آخر تشغيل على main | الحالة | العوائق | ما يراه المالك |
|---|---|---|---|---|---|---|---|---|---|
| تقرير ما قبل الافتتاح | `scripts/build_daily_plan.py`، `options_radar/premarket_report.py`، `price_map_chart.py` | daily-plan | Alpaca SIP تاريخي و IEX؛ خاص (Telegram للمالك)، لا نشر | SIP ≥16 د | SPY وQQQ و12 قيادية؛ SPX/NDX آجل ضمني فقط | 46145931664 (push، 11-28) | MERGED | لم يُختبر حياً | EARLY 16:30 وFINAL 17:00 الرياض |
| متتبع الجلسة | `scripts/run_session_tracker.py`، `options_radar/session_tracker.py` | session-tracker | Alpaca SIP؛ خاص | ≥16 د | 14 رمزاً | لم يعمل بعد على main (أيام العمل فقط) | MERGED | خلل فقدان أحداث نوافذ الفتحات (أُصلح في #469) | الافتتاح، أحداث الجلسة، الساعة الأخيرة، الإغلاق |
| البث اللحظي | `scripts/run_iex_stream.py`، `options_radar/iex_live_alerts.py` | iex-stream | Alpaca IEX WebSocket؛ خاص | ثوانٍ؛ IEX منصة واحدة | 14 رمزاً | لم يعمل بعد | MERGED، والفحص المسبق DEGRADED | الاتصال لا يُثبت إلا حياً | رصد أولي لحظي موسوم «جزئي» |
| صياد العقود | `scripts/run_options_hunter.py`، `options_radar/alpaca_chain.py`، `black76.py` | options-hunter | Alpaca indicative (ليس OPRA)؛ خاص | تأخير indicative | 24 أصلاً، 39,149 عقداً مؤهلاً (run 46126586628) | 46145931699 (push dry run) | MERGED | ليس تدفق صفقات؛ 5 ملخصات يومياً | ملخصات 10:15، 11:30، 13:00، 14:30، 15:30، و`/options` |
| الأسهم الصغيرة | `scripts/run_smallcap_scan.py`، `smallcap_scan.py`، `smallcap_risk.py` | smallcap-scan | Alpaca IEX + SEC (عام)؛ خاص | لقطة IEX | 3,367 سهماً مدرجاً | 46145931779 | MERGED | الأسهم الحرة والتوقف UNKNOWN؛ لا قياس أمامي (لا تخزين) | تنبيه أول مرحلة أو ترقية، و`/smallcaps` |
| الأخبار | `scripts/send_news_flash_24x7.py`، `options_radar/halt_news_engine.py`، `sec_current_feed.py` | news-flash-24x7 | SEC EDGAR (ملك عام) + RSS رسمية؛ Yahoo محجوب | كل ~5 د | 8-K، 6-K، 424B5، S-1، SC 13D | 46145931772 | MERGED | لا رد فعل سعر (لا مصدر أسعار مسموح في هذا المسار) | تنبيه خبر |
| السجلات السريرية والهوية | `scripts/build_clinical_registry_feed.py`، `options_radar/trial_results.py`، `data/entity_graph.json` | clinical feed | ClinicalTrials.gov (عام) | يومي | قائمة الأسماء + 6 علاقات مؤرخة | — | MERGED | خريطة العلاقات صغيرة | أحداث النتائج مع التفسير |
| الأوامر | `scripts/telegram_commands.py` | telegram-commands | — | — | 10 أوامر للمالك فقط | 46145991271 | MERGED | — | `/map /stock /levels /market /status /confirm /options /smallcaps /news /help` |
| الفحص المسبق | `scripts/preflight.py` | settings-check | — | — | كل المحركات | 46145931671: كل المحركات READY عدا البث؛ FULL_READY=false | MERGED | — | سجل Actions |

## ما لا يمكن قياسه على المسار المجاني
- قيمة SPX وNDX النقدية.
- تدفق صفقات OPRA، والبائع والمشتري، وsweeps.
- الأسهم الحرة، وحالة التوقف اللحظية.
- سجل أداء أمامي خاص: لا تخزين مصرح به للمشتقات، فالقياس الأمامي الكامل غير متاح.
