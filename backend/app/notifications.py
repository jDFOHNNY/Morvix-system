"""Email notifications for parent-account lifecycle events."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from backend.app import config


class NotificationDeliveryError(RuntimeError):
    """Raised when a required account notification cannot be handed to SMTP."""


def email_notifications_configured() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_USERNAME and config.SMTP_PASSWORD and (config.EMAIL_FROM or config.SMTP_USERNAME))


def send_parent_acceptance_notice(email: str, name: str) -> None:
    """Send confirmation that a Google account has been accepted as a MORVIX parent."""
    if not email_notifications_configured():
        raise NotificationDeliveryError("Email notifications are not configured.")

    message = EmailMessage()
    message["Subject"] = "Your MORVIX parent account is ready"
    message["From"] = formataddr(("MORVIX", config.EMAIL_FROM or config.SMTP_USERNAME))
    message["To"] = email
    message.set_content(
        f"Hello {name},\n\n"
        "Your Google account has been accepted as the parent account for MORVIX. "
        "You can use it to manage protection settings and review activity for a paired browser extension.\n\n"
        "If you did not create this MORVIX account, contact the person who manages your project.\n\n"
        "MORVIX"
    )

    try:
        if config.SMTP_USE_SSL:
            with smtplib.SMTP_SSL(
                config.SMTP_HOST,
                config.SMTP_PORT,
                timeout=10,
                context=ssl.create_default_context(),
            ) as server:
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                server.send_message(message)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise NotificationDeliveryError("The parent-account notification could not be delivered.") from exc
