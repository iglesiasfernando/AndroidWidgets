from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage


class MailError(RuntimeError):
    pass


@dataclass
class SmtpSettings:
    host: str
    port: int
    user: str
    password: str
    sender: str
    recipients: list[str]

    @classmethod
    def from_env(cls) -> "SmtpSettings":
        missing = [
            k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO")
            if not os.environ.get(k)
        ]
        if missing:
            raise MailError(f"Faltan variables de entorno: {', '.join(missing)}")
        user = os.environ["SMTP_USER"]
        return cls(
            host=os.environ["SMTP_HOST"],
            port=int(os.environ.get("SMTP_PORT", "587")),
            user=user,
            password=os.environ["SMTP_PASSWORD"],
            sender=os.environ.get("MAIL_FROM") or user,
            recipients=[
                r.strip() for r in os.environ["MAIL_TO"].split(",") if r.strip()
            ],
        )


def build_message(settings: SmtpSettings, subject: str, text: str, html: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.sender
    msg["To"] = ", ".join(settings.recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_mail(settings: SmtpSettings, subject: str, text: str, html: str) -> None:
    msg = build_message(settings, subject, text, html)
    context = ssl.create_default_context()
    try:
        if settings.port == 465:
            with smtplib.SMTP_SSL(settings.host, settings.port, context=context, timeout=30) as s:
                s.login(settings.user, settings.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=30) as s:
                s.starttls(context=context)
                s.login(settings.user, settings.password)
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"No se pudo enviar el mail: {e}") from e
