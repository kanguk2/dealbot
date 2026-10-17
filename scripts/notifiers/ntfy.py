"""ntfy push (https://ntfy.sh). The phone app subscribes to the topic; no account needed."""
from __future__ import annotations

from common import http_request
from notifiers.base import Message, Notifier

PRIORITY = {"instant": 4, "daily": 3, "weekly": 2}


class Ntfy(Notifier):
    type = "ntfy"
    label = "ntfy (폰 푸시)"

    @property
    def topic(self) -> str:
        # DEALBOT_NTFY_TOPIC keeps the topic secret when the repo is public.
        return self.env("DEALBOT_NTFY_TOPIC") or self.target

    def missing_env(self) -> list[str]:
        return [] if self.topic else ["DEALBOT_NTFY_TOPIC (또는 notifiers.json target)"]

    def render(self, msg: Message) -> dict:
        body = Message(header="", items=msg.items, body=msg.body, footer=msg.footer,
                       include_summary=msg.include_summary).text().lstrip("\n")
        payload = {"topic": self.topic or "$DEALBOT_NTFY_TOPIC", "title": msg.header,
                   "message": body[:3900] or msg.header,
                   "priority": PRIORITY.get(msg.priority, 3), "tags": ["shopping_cart"]}
        if self.fmt.get("feed_url"):
            payload["click"] = self.fmt["feed_url"]
        elif len(msg.items) == 1:
            payload["click"] = msg.items[0]["url"]
        return payload

    def deliver(self, payload: dict) -> None:
        server = (self.env("DEALBOT_NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
        headers = {}
        if self.env("DEALBOT_NTFY_TOKEN"):
            headers["Authorization"] = f"Bearer {self.env('DEALBOT_NTFY_TOKEN')}"
        http_request("POST", server + "/", json_body=payload, headers=headers)
