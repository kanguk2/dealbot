"""Pushover push (https://pushover.net)."""
from __future__ import annotations

from common import http_request
from notifiers.base import Message, Notifier

PRIORITY = {"instant": 0, "daily": -1, "weekly": -1}


class Pushover(Notifier):
    type = "pushover"
    label = "Pushover (폰 푸시)"
    required_env = ("DEALBOT_PUSHOVER_TOKEN", "DEALBOT_PUSHOVER_USER")

    def render(self, msg: Message) -> dict:
        body = Message(header="", items=msg.items, body=msg.body,
                       include_summary=msg.include_summary).text().lstrip("\n")
        payload = {"title": msg.header[:250], "message": (body or msg.header)[:1024],
                   "priority": PRIORITY.get(msg.priority, 0)}
        if self.fmt.get("feed_url"):
            payload.update(url=self.fmt["feed_url"], url_title="피드 보기")
        return payload

    def deliver(self, payload: dict) -> None:
        form = {"token": self.env("DEALBOT_PUSHOVER_TOKEN"),
                "user": self.env("DEALBOT_PUSHOVER_USER"), **payload}
        http_request("POST", "https://api.pushover.net/1/messages.json", form=form)
