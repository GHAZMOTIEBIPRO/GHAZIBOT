from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from options_radar.providers import load_universe
from options_radar.scanner import OptionsRadar
from options_radar.settings import Settings

st.set_page_config(page_title="Options Radar", layout="wide")
st.title("رادار أفضل عقود الخيارات الأمريكية")
st.caption(
    "فلترة السيولة وVol/OI وGreeks وIV مقابل التذبذب المحقق والمحفز الفني. "
    "النتائج بحثية، وجودة المصدر تظهر مع كل عقد."
)

with st.sidebar:
    st.header("إعدادات الفحص")
    universe_path = st.text_input("ملف الرموز", "data/universe.txt")
    defaults = load_universe(universe_path) if Path(universe_path).exists() else []
    selected = st.multiselect("الأسهم والصناديق", defaults, default=defaults[:12])
    top = st.slider("عدد النتائج", 5, 100, 25, 5)
    send_alerts = st.checkbox("إرسال التنبيهات الجديدة", value=False)
    st.divider()
    st.write("المصدر المختار:", os.getenv("OPTIONS_PROVIDER", "auto"))
    st.write("التنبيهات لا تُرسل إلا عند تفعيل أسرار Telegram أو Discord.")

if st.button("ابدأ الفحص", type="primary", use_container_width=True):
    if not selected:
        st.error("اختر رمزًا واحدًا على الأقل.")
    else:
        try:
            with st.spinner("جلب السلاسل وتحليلها..."):
                result = OptionsRadar(Settings()).scan(
                    selected, top=top, send_alerts=send_alerts,
                    output_csv="results/latest.csv",
                )
            c1, c2, c3 = st.columns(3)
            c1.metric("المصدر", result.provider)
            c2.metric("حالة السوق", result.regime)
            c3.metric("العقود المرشحة", len(result.opportunities))
            if result.alerts:
                st.subheader("🚨 New Independent Setup Alerts")
                for message in result.alerts:
                    st.error(message)
            if result.opportunities.empty:
                st.warning("لم ينجح أي عقد في جميع الفلاتر الحالية.")
            else:
                frame = result.opportunities.copy()
                preferred = [
                    "symbol", "expiration", "strike", "option_type", "score", "rating",
                    "volume", "open_interest", "vol_oi", "iv", "delta", "spread_pct",
                    "aggressor_proxy", "entry_price", "target_1", "target_2", "stop_price",
                    "trade_style", "catalyst", "source", "freshness_label",
                ]
                st.dataframe(frame[[c for c in preferred if c in frame.columns]],
                             use_container_width=True, hide_index=True)
                st.download_button(
                    "تنزيل CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                    file_name="options_radar_latest.csv", mime="text/csv",
                )
            if result.errors:
                with st.expander("أخطاء المصادر"):
                    st.json(result.errors)
        except Exception as exc:
            st.exception(exc)
