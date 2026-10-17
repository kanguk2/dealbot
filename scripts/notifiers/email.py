"""Email over SMTP (Gmail: smtp.gmail.com + app password). Best for weekly digests."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from notifiers.base import Message, Notifier


class Email(Notifier):
    type = "email"
    label = "이메일"
    required_env = ("DEALBOT_SMTP_HOST", "DEALBOT_SMTP_USER", "DEALBOT_SMTP_PASS")

    @property
    def to(self) -> str:
        return self.env("DEALBOT_EMAIL_TO") or self.target or self.env("DEALBOT_SMTP_USER") or ""

    def render(self, msg: Message) -> dict:
        return {"to": self.to or "$DEALBOT_EMAIL_TO", "subject": msg.header, "body": msg.text()}

    def describe(self, payload: dict) -> str:
        return f"To: {payload['to']}\nSubject: {payload['subject']}\n\n{payload['body']}"

    def deliver(self, payload: dict) -> None:
        mail = EmailMessage()
        mail["From"] = self.env("DEALBOT_SMTP_USER")
        mail["To"] = payload["to"]
        mail["Subject"] = payload["subject"]
        mail.set_content(payload["body"])
        host = self.env("DEALBOT_SMTP_HOST")
        port = int(self.env("DEALBOT_SMTP_PORT") or 587)
        user, password = self.env("DEALBOT_SMTP_USER"), self.env("DEALBOT_SMTP_PASS")
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, password)
                s.send_message(mail)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(user, password)
                s.send_message(mail)
