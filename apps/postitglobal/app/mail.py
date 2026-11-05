"""Email the app sends itself (staff invites), through one SMTP account: Gmail's for now."""

import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings


class MailError(Exception):
    """The SMTP server couldn't be reached or refused the message."""


def mail_configured() -> bool:
    return bool(get_settings().smtp_password)


def send_mail(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["From"] = settings.mail_from or settings.smtp_username
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(str(exc)) from exc
