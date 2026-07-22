from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import pandas as pd
import requests

from .settings import Settings

LOGGER = logging.getLogger(__name__)


def _stock_lines(stocks: pd.DataFrame, limit: int = 5) -> list[str]:
    lines: list[str] = []
    for _, row in stocks.head(limit).iterrows():
        lines.append(
            f"• {row['symbol']} | {row['score']:.0f}/100 | دخول {row['entry_low']:.2f}-{row['entry_high']:.2f} "
            f"| أهداف {row['target_1']:.2f}/{row['target_2']:.2f} | وقف {row['stop']:.2f}"
        )
    return lines


def _option_lines(options: pd.DataFrame, limit: int = 5) -> list[str]:
    lines: list[str] = []
    for _, row in options.head(limit).iterrows():
        expiry = pd.to_datetime(row["expiration"]).strftime("%Y-%m-%d")
        lines.append(
            f"• {row['symbol']} {float(row['strike']):g} {str(row['option_type']).upper()} {expiry} "
            f"| {row['score']:.0f}/100 | دخول ${row['entry_price']:.2f} "
            f"| أهداف ${row['target_1']:.2f}/${row['target_2']:.2f}"
        )
    return lines


def build_text_report(stocks: pd.DataFrame, options: pd.DataFrame) -> str:
    stock_lines = _stock_lines(stocks) if not stocks.empty else ["• لا توجد أسهم اجتازت الشروط."]
    option_lines = _option_lines(options) if not options.empty else ["• لا توجد عقود اجتازت الشروط."]
    return "\n".join([
        "📊 تقرير GHAZI Radar اليومي",
        "",
        "أفضل الأسهم:",
        *stock_lines,
        "",
        "أفضل العقود:",
        *option_lines,
        "",
        "النتائج احتمالية وليست ضمانًا. تحقق من السعر اللحظي قبل التنفيذ.",
    ])


def send_telegram_report(settings: Settings, message: str) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False
    response = requests.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json={"chat_id": settings.telegram_chat_id, "text": message[:4000]},
        timeout=20,
    )
    response.raise_for_status()
    return True


def send_email_report(settings: Settings, stocks: pd.DataFrame, options: pd.DataFrame) -> bool:
    if not all([settings.smtp_user, settings.smtp_password, settings.report_email_to]):
        return False
    text = build_text_report(stocks, options)
    rows: list[str] = []
    if not stocks.empty:
        rows.append("<h2>أفضل الأسهم</h2>" + stocks.head(10).to_html(index=False, escape=True))
    if not options.empty:
        columns = [
            column for column in [
                "symbol", "expiration", "strike", "option_type", "score", "entry_price",
                "target_1", "target_2", "stop_price", "catalyst",
            ] if column in options
        ]
        rows.append("<h2>أفضل العقود</h2>" + options[columns].head(10).to_html(index=False, escape=True))
    message = EmailMessage()
    message["Subject"] = "GHAZI Radar — أفضل الأسهم والعقود اليوم"
    message["From"] = settings.smtp_user
    message["To"] = settings.report_email_to
    message.set_content(text)
    message.add_alternative(
        "<html><body dir='rtl'><h1>تقرير GHAZI Radar</h1>"
        + "".join(rows)
        + "<p>النتائج احتمالية وليست ضمانًا. تحقق من السعر اللحظي قبل التنفيذ.</p></body></html>",
        subtype="html",
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=25) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)
    return True


def dispatch_daily_report(
    settings: Settings,
    stocks: pd.DataFrame,
    options: pd.DataFrame,
    send_email: bool = False,
    send_telegram: bool = False,
) -> dict[str, bool]:
    status = {"email": False, "telegram": False}
    text = build_text_report(stocks, options)
    try:
        if send_telegram:
            status["telegram"] = send_telegram_report(settings, text)
    except Exception as exc:
        LOGGER.error("Telegram report failed: %s", exc)
    try:
        if send_email:
            status["email"] = send_email_report(settings, stocks, options)
    except Exception as exc:
        LOGGER.error("Email report failed: %s", exc)
    return status
