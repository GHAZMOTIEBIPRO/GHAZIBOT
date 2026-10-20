"""Links from Telegram alerts to the matching view on the public site.

One place for the site URL and the symbol rule, so every alert path opens
the same chart + decision summary the website shows for that symbol. A
symbol that fails the rule gets no link rather than an escaped one.
"""
from __future__ import annotations

import re
from urllib.parse import quote

SITE_URL = "https://ghazibot.vercel.app"
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,9}")


def chart_url(symbol: str) -> str | None:
    value = str(symbol or "").strip().upper()
    return f"{SITE_URL}/?chart={quote(value)}" if _SYMBOL.fullmatch(value) else None


def chart_link_html(symbol: str, label: str = "الشارت والأدلة على الموقع") -> str:
    url = chart_url(symbol)
    return f'🔗 <a href="{url}">{label}</a>' if url else ""
