import smtplib
from unittest.mock import patch

import pytest

from backend.app import config
from backend.app.notifications import NotificationDeliveryError, email_notifications_configured, send_parent_acceptance_notice


def configure_smtp(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    monkeypatch.setattr(config, "SMTP_USERNAME", "morvix.sender@gmail.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "test-app-password")
    monkeypatch.setattr(config, "EMAIL_FROM", "morvix.sender@gmail.com")
    monkeypatch.setattr(config, "SMTP_USE_SSL", False)


def test_parent_confirmation_email_is_addressed_to_google_account(monkeypatch):
    configure_smtp(monkeypatch)
    with patch("backend.app.notifications.smtplib.SMTP") as smtp:
        send_parent_acceptance_notice("parent@gmail.com", "Test Parent")

    server = smtp.return_value.__enter__.return_value
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("morvix.sender@gmail.com", "test-app-password")
    message = server.send_message.call_args.args[0]
    assert message["To"] == "parent@gmail.com"
    assert "accepted as the parent account" in message.get_content()


def test_email_delivery_failure_prevents_account_acceptance_notice(monkeypatch):
    configure_smtp(monkeypatch)
    with patch("backend.app.notifications.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value.send_message.side_effect = smtplib.SMTPRecipientsRefused({})
        with pytest.raises(NotificationDeliveryError):
            send_parent_acceptance_notice("parent@gmail.com", "Test Parent")


def test_email_delivery_is_not_reported_configured_without_password(monkeypatch):
    configure_smtp(monkeypatch)
    monkeypatch.setattr(config, "SMTP_PASSWORD", "")
    assert not email_notifications_configured()
