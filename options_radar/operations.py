from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .settings import Settings


@dataclass(frozen=True)
class IntegrationStatus:
    name: str
    configured: bool
    required_fields: tuple[str, ...]
    note: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_fields"] = list(self.required_fields)
        return payload


def build_operational_status(settings: Settings) -> dict[str, Any]:
    """Return a safe readiness report without exposing credential values."""

    telegram_ready = bool(settings.telegram_bot_token and settings.telegram_chat_id)
    email_ready = bool(
        settings.smtp_host
        and settings.smtp_port
        and settings.smtp_user
        and settings.smtp_password
        and settings.report_email_to
    )
    discord_ready = bool(settings.discord_webhook_url)

    provider = settings.provider
    provider_ready = True
    provider_note = "Yahoo fallback is available; data may be delayed or unofficial."
    required: tuple[str, ...] = ()
    if provider == "marketdata":
        provider_ready = bool(settings.marketdata_token)
        required = ("MARKETDATA_TOKEN",)
        provider_note = "MarketData.app token required for the selected provider."
    elif provider == "tradier":
        provider_ready = bool(settings.tradier_token)
        required = ("TRADIER_TOKEN", "TRADIER_BASE_URL")
        provider_note = "Tradier token required; sandbox data is delayed and omits Greeks."
    elif provider == "auto":
        provider_note = (
            "Auto mode tries configured providers and falls back to Yahoo when no paid or "
            "brokerage credential is available."
        )

    integrations = [
        IntegrationStatus(
            name="options_data",
            configured=provider_ready,
            required_fields=required,
            note=provider_note,
        ),
        IntegrationStatus(
            name="telegram",
            configured=telegram_ready,
            required_fields=("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
            note=(
                "Instant alerts enabled."
                if telegram_ready
                else "Add a newly rotated bot token and chat ID to GitHub Actions secrets."
            ),
        ),
        IntegrationStatus(
            name="email",
            configured=email_ready,
            required_fields=("SMTP_USER", "SMTP_PASSWORD", "REPORT_EMAIL_TO"),
            note=(
                "Daily email report enabled."
                if email_ready
                else "Daily email remains disabled until SMTP credentials and recipient are added."
            ),
        ),
        IntegrationStatus(
            name="discord",
            configured=discord_ready,
            required_fields=("DISCORD_WEBHOOK_URL",),
            note=(
                "Discord alerts enabled."
                if discord_ready
                else "Optional; no Discord webhook configured."
            ),
        ),
        IntegrationStatus(
            name="sec_identity",
            configured="configure SEC_USER_AGENT" not in settings.sec_user_agent,
            required_fields=("SEC_USER_AGENT",),
            note="SEC requires a descriptive User-Agent and fair-access request behavior.",
        ),
    ]

    return {
        "ready_for_paper_tracking": provider_ready,
        "live_alert_channel_ready": telegram_ready or discord_ready,
        "daily_report_ready": email_ready or telegram_ready,
        "integrations": [item.to_dict() for item in integrations],
        "missing_required_secrets": sorted(
            {
                field
                for item in integrations
                if not item.configured and item.name in {"telegram", "email"}
                for field in item.required_fields
            }
        ),
        "security_note": (
            "Credential values are never written to the public JSON. Store them only in GitHub "
            "Actions secrets."
        ),
    }
