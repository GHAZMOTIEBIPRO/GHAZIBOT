"""Owner-controlled gates for sources whose terms restrict automated use.

Cboe's delayed-quote pages state that downloading delayed quote table
data with auto-extraction programs is strictly prohibited, and Cboe's
market data policies treat single-security, price-like derived data as
fee liable. Until the owner obtains a licence or written permission and
sets the repository variable, automated reads of the Cboe delayed option
JSON are off and every dependent output says why.
"""
from __future__ import annotations

import os

CBOE_VARIABLE = "CBOE_DELAYED_AUTOMATION_APPROVED"
CBOE_BLOCK = {
    "status": "SOURCE_TERMS_BLOCKED",
    "source": "Cboe delayed quotes (cdn.cboe.com)",
    "reason": ("Cboe's delayed-quote terms prohibit automated extraction; automated reads stay off "
               "until a licence or written permission is recorded"),
    "reason_ar": ("شروط Cboe تمنع الاستخراج الآلي لجداول الأسعار المؤجلة؛ الجلب الآلي متوقف حتى "
                  "الحصول على ترخيص أو إذن مكتوب"),
    "enable_with": f"repository variable {CBOE_VARIABLE}=true (only after permission)",
}


def cboe_delayed_automation_allowed() -> bool:
    return os.getenv(CBOE_VARIABLE, "").strip().lower() == "true"
