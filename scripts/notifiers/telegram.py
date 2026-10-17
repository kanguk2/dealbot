"""Telegram Bot API sendMessage (MarkdownV2, link previews off)."""
from __future__ import annotations

import re

from common import http_request
from notifiers.base import Message, Notifier, item_detail

_SPECIAL = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def esc(s: str) -> str:
    return _SPECIAL.sub(r"\\\1", s)


def esc_url(s: str) -> str:
    return s.replace("\\", "\\\\").replace(")", "\\)")


class Telegram(Notifier):
    type = "telegram"
    label = "Telegram"
    required_env = ("DEALBOT_TELEGRAM_TOKEN",)

    @property
    def chat_id(self) -> str:
        # Env wins so a public repo never needs to expose the chat id.
        return self.env("DEALBOT_TELEGRAM_CHAT_ID") or self.target

    def missing_env(self) -> list[str]:
        missing = super().missing_env()
        return missing + ([] if self.chat_id else ["DEALBOT_TELEGRAM_CHAT_ID"])

    def render(self, msg: Message) -> dict:
        lines = [f"*{esc(msg.header)}*"]
        if msg.body:
            lines.append(esc(msg.body))
        for it in msg.items:
            line = f"• [{esc(it['title'])}]({esc_url(it['url'])})"
            if item_detail(it):
                line += f"\n  {esc(item_detail(it))}"
            if msg.include_summary and it.get("summary"):
                line += f"\n  _{esc(it['summary'])}_"
            lines.append(line)
        if msg.footer:
            lines.append(esc(msg.footer))
        return {"chat_id": self.chat_id or "$DEALBOT_TELEGRAM_CHAT_ID",
                "text": "\n".join(lines)[:4096], "parse_mode": "MarkdownV2",
                "link_preview_options": {"is_disabled": True}}

    def deliver(self, payload: dict) -> None:
        token = self.env("DEALBOT_TELEGRAM_TOKEN")
        http_request("POST", f"https://api.telegram.org/bot{token}/sendMessage", json_body=payload)
