"""Discord webhook with one embed per item."""
from __future__ import annotations

from common import http_request
from notifiers.base import Message, Notifier, item_detail

COLOR = {"instant": 0x2F80ED, "daily": 0x27AE60, "weekly": 0x9B51E0}


class Discord(Notifier):
    type = "discord"
    label = "Discord"
    required_env = ("DEALBOT_DISCORD_WEBHOOK",)

    def render(self, msg: Message) -> dict:
        embeds = []
        for it in msg.items[:10]:  # Discord allows 10 embeds per message
            desc = item_detail(it)
            if msg.include_summary and it.get("summary"):
                desc = f"{desc}\n{it['summary']}" if desc else it["summary"]
            embeds.append({"title": it["title"][:256], "url": it["url"],
                           "description": desc[:4000],
                           "color": COLOR.get(msg.priority, 0x2F80ED)})
        content = "\n".join(s for s in (f"**{msg.header}**", msg.body, msg.footer) if s)
        return {"content": content[:2000], "embeds": embeds, "allowed_mentions": {"parse": []}}

    def deliver(self, payload: dict) -> None:
        http_request("POST", self.env("DEALBOT_DISCORD_WEBHOOK"), json_body=payload)
