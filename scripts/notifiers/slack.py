"""Slack Incoming Webhook with Block Kit cards."""
from __future__ import annotations

from common import http_request
from notifiers.base import Message, Notifier, item_detail


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Slack(Notifier):
    type = "slack"
    label = "Slack"
    required_env = ("DEALBOT_SLACK_WEBHOOK",)

    def render(self, msg: Message) -> dict:
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{_esc(msg.header)}*"}}]
        if msg.body:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _esc(msg.body)}})
        for it in msg.items:
            text = f"• <{it['url']}|{_esc(it['title'])}>"
            if item_detail(it):
                text += f"\n{_esc(item_detail(it))}"
            if msg.include_summary and it.get("summary"):
                text += f"\n_{_esc(it['summary'])}_"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}})
        if msg.footer:
            blocks.append({"type": "context",
                           "elements": [{"type": "mrkdwn", "text": _esc(msg.footer)}]})
        return {"text": msg.header, "blocks": blocks[:50]}

    def deliver(self, payload: dict) -> None:
        http_request("POST", self.env("DEALBOT_SLACK_WEBHOOK"), json_body=payload)
