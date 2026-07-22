from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from options_radar.catalysts import CatalystScanner
from options_radar.providers import load_universe
from options_radar.scanner import OptionsRadar
from options_radar.settings import Settings
from options_radar.stocks import StockRadar

st.set_page_config(page_title="GHAZI Market Radar", page_icon="📈", layout="wide")
st.title("📈 GHAZI Radar — أفضل الأسهم والعقود")
st.caption(
    "مصادر مجانية: SEC EDGAR وopenFDA وYahoo Finance. يبدأ النظام بالمحفز، ثم يحلل السهم، "
    "ثم يختار العقود الأعلى سيولة. النتائج تظهر داخل الصفحة فقط ولا توجد رسائل خارجية."
)

settings = Settings()
with st.sidebar:
    st.header("إعدادات بسيطة")
    universe_path = st.text_input("ملف الأسهم", "data/universe.txt")
    defaults = load_universe(universe_path) if Path(universe_path).exists() else []
    selected = st.multiselect("الأسهم المراد فحصها", defaults, default=defaults[:20])
    top_stocks = st.slider("عدد الأسهم", 3, 25, 10)
    top_options = st.slider("عدد العقود", 3, 30, 12)
    st.divider()
    st.write("مصدر العقود:", os.getenv("OPTIONS_PROVIDER", "auto / Yahoo fallback"))
    st.caption("نمط التشغيل: صفحة الويب وسجل GitHub فقط — دون بريد أو Telegram أو Discord.")

run = st.button("ابدأ فحص الأسهم والعقود", type="primary", use_container_width=True)
if run:
    if not selected:
        st.error("اختر سهمًا واحدًا على الأقل.")
    else:
        try:
            progress = st.progress(0, text="قراءة SEC وFDA والأخبار...")
            catalysts = CatalystScanner(settings).scan(selected, lookback_days=7)
            progress.progress(35, text="ترتيب الأسهم فنيًا وربط المحفزات...")
            stock_result = StockRadar(settings).scan(
                selected,
                catalysts=catalysts,
                top=top_stocks,
                output_csv="results/stocks_latest.csv",
            )
            option_symbols = (
                stock_result.opportunities["symbol"].head(max(8, top_stocks)).tolist()
                if not stock_result.opportunities.empty
                else selected[:12]
            )
            progress.progress(65, text="اختيار أفضل العقود للأسهم الأعلى تقييمًا...")
            option_result = OptionsRadar(settings).scan(
                option_symbols,
                top=top_options,
                output_csv="results/options_latest.csv",
                catalysts=catalysts,
            )
            progress.progress(100, text="اكتمل الفحص")
            st.session_state["catalysts"] = catalysts
            st.session_state["stocks"] = stock_result
            st.session_state["options"] = option_result
        except Exception as exc:
            st.exception(exc)

stocks_tab, options_tab, catalysts_tab, rejected_tab = st.tabs([
    "🚀 الأسهم المرشحة",
    "📑 أفضل العقود",
    "📰 محفزات SEC وFDA",
    "⚠️ الأخطاء والقيود",
])

with stocks_tab:
    result = st.session_state.get("stocks")
    if result is None:
        st.info("اضغط زر الفحص لعرض الأسهم المرشحة.")
    elif result.opportunities.empty:
        st.warning("لم يجتز أي سهم الحد الأدنى الحالي.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("حالة السوق", result.regime)
        c2.metric("الأسهم المرشحة", len(result.opportunities))
        c3.metric("إشارات قوية", int(result.opportunities["new_stock_setup"].sum()))
        preferred = [
            "symbol", "score", "rating", "setup_side", "entry_state", "price",
            "entry_low", "entry_high", "target_1", "target_2", "invalidation",
            "rsi", "relative_volume", "sector_etf", "sector_score", "catalyst", "reasons",
        ]
        st.dataframe(result.opportunities[[c for c in preferred if c in result.opportunities]], use_container_width=True, hide_index=True)
        st.download_button("تنزيل الأسهم CSV", result.opportunities.to_csv(index=False).encode("utf-8-sig"), file_name="ghazi_top_stocks.csv", mime="text/csv")

with options_tab:
    result = st.session_state.get("options")
    if result is None:
        st.info("تظهر العقود بعد ترتيب الأسهم تلقائيًا.")
    elif result.opportunities.empty:
        st.warning("لا يوجد عقد اجتاز السيولة والسبريد والدلتا حاليًا.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("مصدر العقود", result.provider)
        c2.metric("حالة السوق", result.regime)
        c3.metric("العقود المرشحة", len(result.opportunities))
        if result.alerts:
            st.subheader("فرص جديدة داخل الرادار")
            for message in result.alerts:
                st.info(message)
        preferred = [
            "symbol", "expiration", "strike", "option_type", "score", "rating",
            "volume", "open_interest", "vol_oi", "iv", "delta", "spread_pct",
            "entry_price", "target_1", "target_2", "stop_price", "reward_risk_1",
            "catalyst", "source", "freshness_label", "new_setup_candidate",
        ]
        st.dataframe(result.opportunities[[c for c in preferred if c in result.opportunities]], use_container_width=True, hide_index=True)
        st.download_button("تنزيل العقود CSV", result.opportunities.to_csv(index=False).encode("utf-8-sig"), file_name="ghazi_top_options.csv", mime="text/csv")

with catalysts_tab:
    frame = st.session_state.get("catalysts")
    if frame is None:
        st.info("سيعرض هذا القسم إفصاحات SEC وأخبار FDA والأخبار المطابقة للكلمات الجوهرية.")
    elif frame.empty:
        st.warning("لم يظهر محفز جوهري حديث للأسهم المختارة.")
    else:
        positive_only = st.toggle("إظهار المحفزات الإيجابية فقط", value=False)
        shown = frame[frame["score"] > 0] if positive_only else frame
        preferred = ["event_date", "symbol", "score", "category", "headline", "source", "form", "confidence", "evidence", "url"]
        st.dataframe(shown[[c for c in preferred if c in shown]], use_container_width=True, hide_index=True, column_config={"url": st.column_config.LinkColumn("المصدر الرسمي")})

with rejected_tab:
    stock_result = st.session_state.get("stocks")
    option_result = st.session_state.get("options")
    if stock_result and stock_result.errors:
        st.subheader("أخطاء بيانات الأسهم")
        st.json(stock_result.errors)
    if option_result and option_result.errors:
        st.subheader("أخطاء بيانات العقود")
        st.json(option_result.errors)
    st.warning("بيانات Yahoo المجانية قد تكون متأخرة، وVol/OI لا يثبت وحده شراءً مؤسسيًا. تحقق من السعر الحي قبل التنفيذ.")
