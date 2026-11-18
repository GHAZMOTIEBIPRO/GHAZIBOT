"""Shared Arabic presentation for GHAZI RADAR Telegram messages (HTML parse mode).

Why this exists: messages were hard to read. They mixed raw English codes, UTC/ISO stamps and
`|`-separated fields, and a line starting with a Latin word ("GHAZI RADAR", "NVDA") was laid
out left-to-right inside an Arabic chat.

Rules applied here:
- Direction: a paragraph takes the direction of its first strong character (Unicode
  Bidirectional Algorithm, UAX #9). Every line whose first strong character is not
  Arabic gets a RIGHT-TO-LEFT MARK (U+200F). The mark is supported by every Telegram client,
  unlike the newer isolate controls (LRI/RLI/FSI), whose support W3C reports as uneven.
- Only tags Telegram's HTML mode accepts are used (<b>, <a>). Lines are joined with "\\n"
  (no <br>, no lists), and dynamic text is escaped by the callers.
- Time: the market's own clock (New York) plus the reader's clock (Riyadh), 12-hour form
  with ص / م. A date is a weekday and day-month in Arabic.
- Words, not codes: every event kind has an Arabic name, plus a short "why it matters" and a
  "what to watch". These are fixed explanations of the event type and never new facts,
  numbers or price direction (skill ghazi-market-analysis).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from html import unescape
from zoneinfo import ZoneInfo

RLM = "\u200f"
LRM = "\u200e"
NEW_YORK = ZoneInfo("America/New_York")
RIYADH = ZoneInfo("Asia/Riyadh")
TELEGRAM_LIMIT = 4096

WEEKDAYS_AR = ("الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد")
MONTHS_AR = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
             "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")

DISCLAIMER = "⚠️ للمتابعة والبحث فقط — ليست توصية شراء أو بيع."

SOURCE_AR = {
    "openFDA": "إدارة الغذاء والدواء الأمريكية (FDA)",
    "SEC EDGAR": "هيئة الأوراق المالية الأمريكية (SEC)",
    "ClinicalTrials.gov": "سجل التجارب السريرية الأمريكي (ClinicalTrials.gov)",
    "Company IR": "علاقات المستثمرين في الشركة",
    "Federal Register": "السجل الفيدرالي الأمريكي",
}
IMPORTANCE_AR = {"HIGH": "عالية", "MEDIUM": "متوسطة", "LOW": "منخفضة"}

# kind -> (Arabic name, why it matters, what to watch). Generic explanations of the event type.
EVENT_KINDS: dict[str, tuple[str, str, str]] = {
    "FDA_APPROVAL": ("موافقة FDA على دواء",
                     "الموافقة تسمح ببيع المنتج في السوق الأمريكي.",
                     "حجم السوق المتوقع للمنتج وتعليق الشركة على موعد الإطلاق."),
    "FDA_SUPPLEMENT": ("تعديل على موافقة دواء قائمة",
                       "تعديل على منتج موافق عليه مسبقًا (استخدام أو جرعة أو تصنيع)؛ أثره عادة أصغر من موافقة جديدة.",
                       "هل يضيف التعديل استخدامًا جديدًا يوسّع المبيعات."),
    "FDA_RECALL": ("سحب منتج بقرار FDA",
                   "السحب قد يعني تكاليف أو ضررًا للسمعة حسب خطورته.",
                   "درجة السحب (الدرجة الأولى هي الأخطر) وحصة المنتج من إيرادات الشركة."),
    "DILUTION_RISK": ("خطر طرح أسهم جديدة (تخفيف الملكية)",
                      "زيادة عدد الأسهم قد تضغط على سعر السهم.",
                      "حجم الطرح وسعره مقارنة بسعر السهم الحالي."),
    "LISTING_NOTICE": ("إشعار من البورصة بشأن الإدراج",
                       "قد يتعلق باستمرار إدراج السهم في البورصة.",
                       "المهلة الممنوحة للشركة وخطتها لمعالجة الإشعار."),
    "MATERIAL_AGREEMENT": ("اتفاقية جوهرية",
                           "قد تغيّر إيرادات الشركة أو التزاماتها.",
                           "قيمة الاتفاقية ومدتها والطرف الآخر في نص الإفصاح."),
    "EARNINGS_RELEASE": ("إعلان نتائج مالية",
                         "النتائج عادة تسبق أكبر تحركات السهم.",
                         "الإيرادات والأرباح والتوجيهات المستقبلية مقارنة بالتوقعات."),
    "CHARTER_OR_REVERSE_SPLIT_REVIEW": ("تعديل نظام أساسي أو دمج أسهم عكسي",
                                        "غالبًا خطوة للحفاظ على شروط الإدراج.",
                                        "نسبة الدمج وتاريخ التنفيذ."),
    "TRIAL_RESULTS_POSTED": ("نشر نتائج تجربة سريرية",
                             "نتائج منشورة في السجل الرسمي؛ اتجاهها (إيجابي أو سلبي) غير مقيّم هنا.",
                             "النتيجة الأساسية في السجل وبيان الشركة عنها."),
    "TRIAL_STATUS_REVIEW": ("تغيّر حالة تجربة سريرية",
                            "إيقاف أو تعليق دراسة قد يؤثر على منتج قيد التطوير، والسبب غير مثبت بعد.",
                            "بيان الشركة عن سبب التغيير."),
    "INSIDER_FILING": ("إفصاح تداول المطلعين",
                       "يكشف شراء أو بيع مسؤولي الشركة لأسهمها (إفصاح متأخر وليس مركزًا حاليًا).",
                       "الحجم ونوع العملية (شراء من السوق أم منح أسهم)."),
    "PERIODIC_REPORT": ("تقرير دوري",
                        "تقرير مالي ربعي أو سنوي رسمي.",
                        "تغيّر الإيرادات والسيولة والمخاطر المذكورة."),
}

_TAG = re.compile(r"<[^>]+>")


def first_strong(text: str) -> str | None:
    """'R' for Arabic/Hebrew, 'L' for Latin, None when the line has no strong character."""
    for char in unescape(_TAG.sub("", text)):
        kind = unicodedata.bidirectional(char)
        if kind in ("R", "AL"):
            return "R"
        if kind == "L":
            return "L"
    return None


def rtl_line(line: str) -> str:
    """Make the line a right-to-left paragraph regardless of its first word."""
    if not line or line.startswith(RLM) or first_strong(line) == "R":
        return line
    return RLM + line


TELEGRAM_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre",
                 "blockquote", "tg-spoiler", "span"}
_TAG_PARTS = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9-]*)[^>]*>")


def check_html(text: str) -> None:
    """Raise ValueError for tags Telegram's HTML mode rejects, unbalanced tags or a tag nested in itself."""
    stack: list[str] = []
    for closing, name in _TAG_PARTS.findall(text):
        name = name.lower()
        if name not in TELEGRAM_TAGS:
            raise ValueError(f"unsupported Telegram tag <{name}>")
        if closing:
            if not stack or stack[-1] != name:
                raise ValueError(f"unbalanced </{name}>")
            stack.pop()
        else:
            if name in stack:
                raise ValueError(f"<{name}> nested inside itself")
            stack.append(name)
    if stack:
        raise ValueError(f"unclosed <{stack[-1]}>")


def render(lines: list[str]) -> str:
    """Join message lines; each line becomes a right-to-left paragraph. Blank lines are kept."""
    text = "\n".join(rtl_line(line) for line in lines)
    if len(text) > TELEGRAM_LIMIT:
        raise ValueError(f"Telegram message too long: {len(text)} > {TELEGRAM_LIMIT}")
    check_html(text)
    return text


_MIXED_TOKEN = re.compile(r"(?<![\w\u200e])(\d+[-./]?[A-Za-z][\w./-]*|[A-Za-z][\w]*[-./]\d[\w./-]*)")


def ltr_tokens(text: str) -> str:
    """Keep mixed digit/Latin tokens such as '8-K', '10-Q' or 'S-1' in their written order.

    Inside Arabic text the bidi algorithm turns a leading number into an Arabic number and
    shows '8-K' as 'K-8'. Surrounding the token with LEFT-TO-RIGHT MARKs makes it one
    left-to-right run. Apply to plain text only (before wrapping it in tags).
    """
    return _MIXED_TOKEN.sub(lambda m: f"{LRM}{m.group(0)}{LRM}", text)


def ticker(symbol: str) -> str:
    """Bold ticker followed by a left-to-right mark so adjacent Arabic punctuation stays put."""
    from html import escape
    return f"<b>{escape(str(symbol))}</b>{LRM}"


def price(value: float) -> str:
    return f"{float(value):,.2f}"


def date_ar(value: date | datetime | str, *, year: bool = True) -> str:
    """'الأربعاء 18 نوفمبر 2026' (or without the year). Accepts ISO date strings."""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    if isinstance(value, datetime):
        value = value.date()
    text = f"{WEEKDAYS_AR[value.weekday()]} {value.day} {MONTHS_AR[value.month - 1]}"
    return f"{text} {value.year}" if year else text


def day_month_ar(value: date | str) -> str:
    """'18 نوفمبر'."""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.day} {MONTHS_AR[value.month - 1]}"


def clock_ar(moment: datetime, zone: ZoneInfo) -> str:
    """'10:05 ص' in the given zone."""
    if moment.tzinfo is None:
        raise ValueError("aware datetime required")
    local = moment.astimezone(zone)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'ص' if local.hour < 12 else 'م'}"


def when_ar(moment: datetime) -> str:
    """'10:05 ص نيويورك (6:05 م الرياض)'."""
    return f"{clock_ar(moment, NEW_YORK)} نيويورك ({clock_ar(moment, RIYADH)} الرياض)"


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def days_ar(count: int) -> str:
    """Arabic number agreement for days: يوم واحد / يومين / 3 أيام / 11 يومًا."""
    n = int(count)
    if n == 1:
        return "يوم واحد"
    if n == 2:
        return "يومين"
    if 3 <= n <= 10:
        return f"{n} أيام"
    return f"{n} يومًا"


def stocks_ar(count: int) -> str:
    """'سهم واحد' / 'سهمين' / '5 أسهم' / '60 سهمًا'."""
    n = int(count)
    if n == 1:
        return "سهم واحد"
    if n == 2:
        return "سهمين"
    if 3 <= n <= 10:
        return f"{n} أسهم"
    return f"{n} سهمًا"


def event_kind(kind: str) -> tuple[str, str, str]:
    """(name, why, watch); unknown kinds get a neutral Arabic label, never the raw code."""
    return EVENT_KINDS.get(kind, ("حدث رسمي", "حدث منشور في مصدر رسمي.", "تفاصيل الحدث في الوثيقة الرسمية."))
