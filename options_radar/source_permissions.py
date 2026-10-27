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

Added 2026-10-21 (runner probe 39521600490):

- NasdaqTrader.com copyright statement (read in full): the Content "may not
  be copied, reproduced, transmitted, displayed, performed, distributed,
  rented, sublicensed, altered, stored for subsequent use or otherwise used
  in whole or in part in any manner without the prior written consent of
  Nasdaq", and the reports and data there "are proprietary to The Nasdaq,
  Inc.". Covers the Symbol Directory files and the trade-halt RSS feed.
- OCC: theocc.com answers the runner with 403, so its Terms and Conditions
  could not be read in full; the search-index text of that official page
  lists "use or launch any automated system, including robots, spiders,
  or offline readers, to access the Services" as prohibited conduct.
  Unreadable terms are UNKNOWN, and UNKNOWN is not permission.
- FINRA API Terms of Service (read in full): "Developer shall access the
  Licensed APIs and the Licensed Data solely using access credentials
  provided to Developer by FINRA"; the finra.org Terms of Use forbid
  "data mining, scraping or harvesting tools (including robots)" and limit
  content to "non-commercial personal or professional use". The project
  calls api.finra.org without FINRA credentials.
- FRED: the terms pages time out from the runner (UNKNOWN); the search-index
  text of the official API terms forbids storing, caching or archiving FRED
  content, which persistent state would do.
- BLS: every www.bls.gov terms page answers the runner with 403, also with a
  declared User-Agent (runs 39521600490, 39522604250), so the API terms
  could not be read; UNKNOWN is not permission. An owner who reads the
  official BLS copyright and API terms pages may record them and open the
  gate; that records the provider's published terms, not the owner's own
  approval.

Added 2026-10-21 (runner probe 39523530990):

- Google Terms of Service (read in full) forbid "using automated means to
  access content from any of our services in violation of the
  machine-readable instructions on our web pages (for example, robots.txt
  files that disallow crawling ...)"; news.google.com/robots.txt is
  ``User-agent: * Disallow: /`` and does not allow /rss/. Google also says
  third-party content in Google News may not be used "without that person
  or organization's permission".
- PR Newswire Terms of Use (read in full): users may not "use any robot,
  spider, site search/retrieval application, or other manual or automatic
  device or process to access, search, download, retrieve, index or 'data
  mine' any content", nor "reproduce, distribute, ... 'scrape,' republish
  or retransmit" content without express prior written permission.
  GlobeNewswire answers the runner with 403 and Business Wire timed out, so
  their terms are UNKNOWN; the three wires share one gate.
- GDELT (read in full) is open for "unlimited and unrestricted use ... of
  any kind without fee" with a citation and link to gdeltproject.org, so it
  is not gated.
"""
from __future__ import annotations

import os

CBOE_VARIABLE = "CBOE_DELAYED_AUTOMATION_APPROVED"
YAHOO_VARIABLE = "YAHOO_AUTOMATED_ACCESS_APPROVED"
NASDAQ_WEB_VARIABLE = "NASDAQ_WEB_AUTOMATION_APPROVED"
COMMUNITY_GEX_VARIABLE = "COMMUNITY_GEX_DATA_APPROVED"
OCC_VARIABLE = "OCC_MARKET_DATA_AUTOMATION_APPROVED"
NASDAQTRADER_VARIABLE = "NASDAQTRADER_AUTOMATION_APPROVED"
FINRA_API_VARIABLE = "FINRA_API_AUTOMATION_APPROVED"
FRED_VARIABLE = "FRED_AUTOMATION_APPROVED"
BLS_VARIABLE = "BLS_AUTOMATION_APPROVED"
GOOGLE_NEWS_VARIABLE = "GOOGLE_NEWS_AUTOMATION_APPROVED"
PRESS_WIRE_VARIABLE = "PRESS_WIRE_RSS_APPROVED"

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
    "occ_market_data": {
        "variable": OCC_VARIABLE,
        "source": "OCC market data reports (marketdata.theocc.com)",
        "reason": ("OCC's terms list launching any automated system (robots, spiders) to access its services "
                   "as prohibited conduct, and theocc.com refuses automated readers, so its full terms could "
                   "not be verified; automated reads stay off until OCC grants a licence or permission"),
        "reason_ar": ("شروط OCC تعدّ تشغيل أي نظام آلي للوصول إلى خدماتها سلوكًا محظورًا، وموقعها يرفض القراءة "
                      "الآلية فلم يمكن التحقق من نصها كاملًا؛ الجلب الآلي متوقف حتى ترخيص أو إذن من OCC"),
    },
    "nasdaqtrader": {
        "variable": NASDAQTRADER_VARIABLE,
        # Nasdaq Listed (nasdaqlisted.txt) is opened by its own product notice (PRODUCT_GRANTS);
        # this gate covers the files no product notice settles (PRODUCT_UNRESOLVED) and the halt RSS.
        "source": "NasdaqTrader.com (files not covered by a product notice, trade-halt RSS)",
        "reason": ("NasdaqTrader.com content and reports may not be copied, displayed, distributed, stored for "
                   "subsequent use or otherwise used without Nasdaq's prior written consent; automated reads "
                   "stay off until Nasdaq grants permission"),
        "reason_ar": ("محتوى NasdaqTrader.com وتقاريره لا يجوز نسخها أو عرضها أو توزيعها أو تخزينها أو استخدامها "
                      "دون موافقة Nasdaq الكتابية المسبقة؛ الجلب الآلي متوقف حتى إذن Nasdaq"),
    },
    "finra_api": {
        "variable": FINRA_API_VARIABLE,
        "source": "FINRA API (api.finra.org Reg SHO daily data)",
        "reason": ("FINRA's API terms allow access only with FINRA-issued credentials and its website terms "
                   "forbid scraping and limit use to non-commercial personal use; uncredentialed automated "
                   "reads stay off until a FINRA developer account and terms acceptance are recorded"),
        "reason_ar": ("شروط واجهة FINRA تسمح بالوصول فقط ببيانات اعتماد صادرة من FINRA وشروط موقعها تمنع الكشط "
                      "وتقصر الاستخدام على غير التجاري؛ الجلب الآلي دون اعتماد متوقف حتى تسجيل حساب مطوّر وقبول الشروط"),
    },
    "fred": {
        "variable": FRED_VARIABLE,
        "source": "FRED API (api.stlouisfed.org)",
        "reason": ("FRED's terms could not be read from the runner and its official API terms forbid storing, "
                   "caching or archiving FRED content; automated reads stay off until the terms are verified "
                   "for this use"),
        "reason_ar": ("تعذر قراءة شروط FRED من خادم التشغيل، وشروط واجهتها الرسمية تمنع تخزين محتواها أو "
                      "تخزينه مؤقتًا أو أرشفته؛ الجلب الآلي متوقف حتى التحقق من الشروط لهذا الاستخدام"),
    },
    "bls": {
        "variable": BLS_VARIABLE,
        "source": "U.S. Bureau of Labor Statistics (api.bls.gov, release calendar)",
        "reason": ("BLS terms pages refuse the runner (HTTP 403), so the API terms of service could not be "
                   "verified; automated reads stay off until the published BLS terms are recorded for this use"),
        "reason_ar": ("صفحات شروط BLS ترفض خادم التشغيل (403) فلم يمكن التحقق من شروط الواجهة؛ الجلب الآلي "
                      "متوقف حتى تسجيل شروط BLS المنشورة لهذا الاستخدام"),
    },
    "google_news": {
        "variable": GOOGLE_NEWS_VARIABLE,
        "source": "Google News RSS search (news.google.com/rss)",
        "reason": ("Google's terms forbid automated access that ignores robots.txt, and news.google.com "
                   "robots.txt disallows the RSS search paths; publisher content there also needs the "
                   "publisher's permission; automated reads stay off"),
        "reason_ar": ("شروط Google تمنع الوصول الآلي المخالف لملف robots.txt، وملف news.google.com يمنع مسارات "
                      "RSS، ومحتوى الناشرين يحتاج إذنهم؛ الجلب الآلي متوقف"),
    },
    "press_wire_rss": {
        "variable": PRESS_WIRE_VARIABLE,
        "source": "Press-wire RSS (PR Newswire, GlobeNewswire, Business Wire)",
        "reason": ("PR Newswire's terms forbid robots or automatic processes that download or index its "
                   "content and any republishing without written permission; GlobeNewswire and Business Wire "
                   "terms could not be read from the runner; automated reads stay off until permission"),
        "reason_ar": ("شروط PR Newswire تمنع الأدوات الآلية لتنزيل محتواها أو فهرسته وإعادة نشره دون إذن مكتوب، "
                      "وتعذرت قراءة شروط GlobeNewswire وBusiness Wire؛ الجلب الآلي متوقف حتى الإذن"),
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


# Product-level grants: a provider's own notice for one product, quoted verbatim.
# They open only the named product; every other file of the same site keeps its gate.
# Read in full on the runner, probe run 40562010708 (2026-10-27).
NASDAQ_EVENTS_DATA_NOTICE = (
    "Nasdaq Events Data: The data related to Nasdaq Security Status Updates, Nasdaq Ex-Date, When "
    "Distributed/When Issued, and Nasdaq Listed has been created, collected, validated, processed, generated "
    "and/or recorded by Nasdaq. The data made available herein is provided as it exists in Nasdaq's records "
    "without restriction or any further licensing requirement, notwithstanding Nasdaq Terms of Services "
    "( https://www.nasdaq.com/legal ).")
PRODUCT_GRANTS: dict[str, dict[str, str]] = {
    "nasdaqtrader_nasdaq_listed": {
        "url": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
        "product": "Nasdaq Listed (Symbol Directory nasdaqlisted.txt, incl. its Financial Status field)",
        "notice_url": "https://www.nasdaqtrader.com/trader.aspx?id=symbollookup",
        "evidence": NASDAQ_EVENTS_DATA_NOTICE,
        "evidence_run": "40562010708",
    },
}
# Products of the same site whose terms are not settled by a product notice. Not a
# confirmed ban: the exact open question is recorded and the gate stays closed.
PRODUCT_UNRESOLVED: dict[str, dict[str, str]] = {
    "nasdaqtrader_other_listed": {
        "url": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
        "question": ("Does the Events Data notice's 'Nasdaq Listed' cover the Other-Exchange Listed file "
                     "(securities listed on NYSE and other exchanges), or does the site copyright notice "
                     "(CopyDisclaimMain: no copying or storage without written consent) govern it?"),
        "question_ar": ("هل تشمل عبارة «Nasdaq Listed» في إشعار Events Data ملف الأوراق المدرجة في بورصات أخرى، "
                        "أم يحكمه إشعار حقوق النشر العام للموقع؟"),
    },
    "nasdaqtrader_market_participants": {
        "url": "ftp://ftp.nasdaqtrader.com/symboldirectory/mpidlist.txt",
        "question": "Neither product notice names the Market Participants file.",
        "question_ar": "لا يذكر أي إشعار منتج ملف المشاركين في السوق.",
    },
    "nasdaqtrader_options_files": {
        "url": "ftp://ftp.nasdaqtrader.com/SymbolDirectory/phlxoptions.csv",
        "question": "Neither product notice names the PHLX options / strikes / PBOT files.",
        "question_ar": "لا يذكر أي إشعار منتج ملفات خيارات PHLX وأسعار التنفيذ وPBOT.",
    },
}
# Restricted by its own product notice (not by another product's text).
PRODUCT_RESTRICTED: dict[str, dict[str, str]] = {
    "nasdaqtrader_fund_network": {
        "url": "ftp://ftp.nasdaqtrader.com/symboldirectory/mfundslist.txt",
        "evidence": ("Nasdaq Fund Network - ... Nasdaq and its licensors retain all right, title and interest "
                     "information including, but not limited to the symbols. The data and information made "
                     "available for internal non-commercial usage only unless separately licensed from Nasdaq."),
    },
}


def product_allowed(product: str) -> bool:
    """True only for a product opened by its own provider notice (PRODUCT_GRANTS)."""
    return product in PRODUCT_GRANTS


def gate_status() -> dict[str, dict[str, object]]:
    return {name: {"allowed": allowed(name), **block_record(name)} for name in GATES}


CBOE_BLOCK = block_record("cboe_delayed")


def cboe_delayed_automation_allowed() -> bool:
    return allowed("cboe_delayed")
