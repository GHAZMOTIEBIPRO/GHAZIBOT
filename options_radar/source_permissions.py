"""Owner-controlled gates for sources whose terms restrict automated use.

Each gate is closed unless its repository variable is exactly ``true``,
and that variable may only be set after the provider grants a licence or
written permission; the owner's own approval is not a substitute. Every
automated read of a gated source calls :func:`require`, so a closed gate
stops the request before it leaves the runner and dependent outputs can
say why the data is missing.

The reasons below quote the providers' full official documents as fetched
from a GitHub runner on 2026-10-20 (see
docs/OPEN_SOURCE_AND_DATA_SOURCE_DECISIONS.md):

- Cboe delayed quotes: "IT IS STRICTLY PROHIBITED TO DOWNLOAD DELAYED QUOTE
  TABLE DATA FROM THIS WEB SITE BY USING AUTO-EXTRACTION PROGRAMS".
- Yahoo Terms of Service: users must not "access or collect data ... from our
  Services using any automated means ... for any purpose without our express,
  prior permission"; robots.txt on query1/query2.finance.yahoo.com (the hosts
  yfinance and yahooquery call) is ``Disallow: /``.
- Community SPX gamma feeds on GitHub (dhawalc/spx-gamma-levels,
  Alexduanran/spx-0dte-archive): no licence file (GitHub reports
  NOASSERTION); one README claims CC BY 4.0 but neither names a licensed
  upstream for the option chains it is computed from, and the archive
  describes its inputs as perishable feeds. Rights are UNKNOWN, and UNKNOWN
  is not permission.
- Nasdaq.com terms: licence "solely for your personal, non-commercial use"
  and users must not use "any process, whether automated or manual, to
  capture data or content from the Service"; api.nasdaq.com robots.txt is
  ``Disallow: /``.
"""
from __future__ import annotations

import os

CBOE_VARIABLE = "CBOE_DELAYED_AUTOMATION_APPROVED"
YAHOO_VARIABLE = "YAHOO_AUTOMATED_ACCESS_APPROVED"
NASDAQ_WEB_VARIABLE = "NASDAQ_WEB_AUTOMATION_APPROVED"
COMMUNITY_GEX_VARIABLE = "COMMUNITY_GEX_DATA_APPROVED"

GATES: dict[str, dict[str, str]] = {
    "cboe_delayed": {
        "variable": CBOE_VARIABLE,
        "source": "Cboe delayed quotes (cdn.cboe.com)",
        "reason": ("Cboe's delayed-quote terms prohibit automated extraction; automated reads stay off "
                   "until a licence or written permission is recorded"),
        "reason_ar": ("شروط Cboe تمنع الاستخراج الآلي لجداول الأسعار المؤجلة؛ الجلب الآلي متوقف حتى "
                      "الحصول على ترخيص أو إذن مكتوب"),
    },
    "yahoo": {
        "variable": YAHOO_VARIABLE,
        "source": "Yahoo Finance (yfinance / yahooquery via query1/query2.finance.yahoo.com)",
        "reason": ("Yahoo's Terms of Service forbid accessing or collecting data by automated means for any "
                   "purpose without Yahoo's express prior permission, and robots.txt on the Yahoo Finance "
                   "query hosts disallows every path; automated reads stay off until Yahoo grants permission"),
        "reason_ar": ("شروط Yahoo تمنع جمع البيانات بأي وسيلة آلية لأي غرض دون إذن مسبق صريح، وملف "
                      "robots.txt لخوادم Yahoo Finance يمنع كل المسارات؛ الجلب الآلي متوقف حتى إذن Yahoo"),
    },
    "nasdaq_web": {
        "variable": NASDAQ_WEB_VARIABLE,
        "source": "Nasdaq.com website APIs (api.nasdaq.com)",
        "reason": ("Nasdaq.com terms grant a personal, non-commercial licence and forbid automated or manual "
                   "capture of site data, and api.nasdaq.com robots.txt disallows every path; automated "
                   "reads stay off until Nasdaq grants permission"),
        "reason_ar": ("شروط Nasdaq.com للاستخدام الشخصي غير التجاري فقط وتمنع التقاط بيانات الموقع آليًا أو "
                      "يدويًا، وملف robots.txt لـ api.nasdaq.com يمنع كل المسارات؛ الجلب الآلي متوقف حتى إذن Nasdaq"),
    },
    "community_gex": {
        "variable": COMMUNITY_GEX_VARIABLE,
        "source": "Community SPX gamma feeds (dhawalc/spx-gamma-levels, Alexduanran/spx-0dte-archive)",
        "reason": ("These GitHub feeds have no licence file and do not name a licensed upstream for the "
                   "option chains they are computed from; their data rights are unknown, so automated "
                   "reads stay off until the rights are verified"),
        "reason_ar": ("مستودعات جاما المجتمعية على GitHub بلا ملف ترخيص ولا تذكر مصدرًا مرخصًا لسلاسل الخيارات "
                      "التي تُحسب منها؛ حقوقها غير معروفة، فالقراءة الآلية متوقفة حتى التحقق منها"),
    },
}


class SourceTermsBlocked(RuntimeError):
    """Raised before any request to a source whose gate is closed."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.block = block_record(source)
        super().__init__(f"SOURCE_TERMS_BLOCKED: {self.block['source']}: {self.block['reason']}")


def allowed(source: str) -> bool:
    gate = GATES[source]
    return os.getenv(gate["variable"], "").strip().lower() == "true"


def block_record(source: str) -> dict[str, str]:
    gate = GATES[source]
    return {
        "status": "SOURCE_TERMS_BLOCKED",
        "source": gate["source"],
        "reason": gate["reason"],
        "reason_ar": gate["reason_ar"],
        "enable_with": f"repository variable {gate['variable']}=true (only after the provider's permission)",
    }


def require(source: str) -> None:
    if not allowed(source):
        raise SourceTermsBlocked(source)


def blocked_report(source: str, *, schema: str, generated_at: str) -> dict[str, object]:
    """Replacement for a public file whose only input is a closed source.

    Overwriting keeps previously collected provider data off the public
    site instead of letting it age in place under a warning label.
    """
    return {
        "schema": schema,
        "generated_at": generated_at,
        **block_record(source),
        "symbols": {},
        "coverage": {"symbols": 0},
        "execution_authority": False,
    }


def gate_status() -> dict[str, dict[str, object]]:
    return {name: {"allowed": allowed(name), **block_record(name)} for name in GATES}


CBOE_BLOCK = block_record("cboe_delayed")


def cboe_delayed_automation_allowed() -> bool:
    return allowed("cboe_delayed")
