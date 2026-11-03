"""Shared SMTP transport. Credentials and message contents never enter delivery errors."""

import smtplib
import ssl
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage
from typing import Annotated

from pydantic import AfterValidator

from app.config import Settings


def normalize_email(value: str) -> str:
    value = value.strip()
    try:
        address = Address(addr_spec=value)
    except (ValueError, IndexError, HeaderParseError) as error:
        raise ValueError("Enter a valid email address") from error
    if (
        not value.isascii()
        or len(value) > 254
        or len(address.username) > 64
        or not address.username
        or not address.domain
        or "." not in address.domain
        or any(char.isspace() or ord(char) < 32 for char in value)
        or address.addr_spec != value
    ):
        raise ValueError("Enter a valid email address")
    return value.lower()


EmailAddress = Annotated[str, AfterValidator(normalize_email)]


def email_enabled(settings: Settings) -> bool:
    return bool(settings.smtp_host and settings.smtp_from)


def send_email(settings: Settings, recipient: str, subject: str, body: str) -> None:
    if not email_enabled(settings):
        raise ValueError("Email delivery is not configured")
    message = EmailMessage()
    message["From"] = Address(
        display_name=settings.smtp_from_name, addr_spec=normalize_email(settings.smtp_from)
    )
    message["To"] = normalize_email(recipient)
    message["Subject"] = subject
    message.set_content(body)
    connection = (
        smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=10, context=ssl.create_default_context()
        )
        if settings.smtp_security == "ssl"
        else smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
    )
    with connection as smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            smtp.login(
                settings.smtp_username,
                settings.smtp_password.get_secret_value() if settings.smtp_password else "",
            )
        smtp.send_message(message)
