"""Notifier plugin interface and the shared message model.

A plugin is one module in scripts/notifiers/ defining a ``Notifier`` subclass with a
unique ``type`` (matches notifiers.json ``type``). Implement ``render`` (Message ->
channel payload) and ``deliver`` (payload -> network). ``send`` handles splitting,
the 3-message cap, one retry, dry-run and missing secrets.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

MAX_MESSAGES = 3
PRIORITY_LABEL = {"instant": "새 딜", "daily": "어제 모은 딜", "weekly": "지난 주 딜"}
SOURCE_LABEL = {"epic_free": "에픽", "search": "검색"}
RSS_LABEL = {"ruliweb": "루리웹", "ppomppu": "뽐뿌", "quasarzone": "퀘이사존", "algumon": "알구몬"}


def source_label(source: str | None) -> str:
    if not source:
        return "?"
    if source in SOURCE_LABEL:
        return SOURCE_LABEL[source]
    if source.startswith("rss:"):
        feed = source[4:]
        return RSS_LABEL.get(feed.split("_")[0], feed)
    return source


def won(n: int) -> str:
    return f"{n:,}원"


def price_text(it: dict) -> str | None:
    p, o, pct = it.get("price_krw"), it.get("original_price_krw"), it.get("discount_pct")
    if p == 0:
        return f"무료 (정가 {won(o)})" if o else "무료"
    parts = []
    if p is not None:
        parts.append(won(p))
    if pct:
        parts.append(f"-{pct}%")
    if o and p is not None and o > p:
        parts.append(f"정가 {won(o)}")
    return " ".join(parts) or None


def short_date(iso: str | None) -> str | None:
    if not iso or len(iso) < 10:
        return None
    return f"{int(iso[5:7])}/{int(iso[8:10])}"


def item_detail(it: dict) -> str:
    """'무료 (정가 32,000원) · 에픽 · ~10/23'"""
    ends = short_date(it.get("ends"))
    bits = [price_text(it), source_label(it.get("source")), f"~{ends}" if ends else None]
    return " · ".join(b for b in bits if b)


@dataclass
class Message:
    header: str
    items: list = field(default_factory=list)
    body: str = ""            # free text (alerts); items messages leave it empty
    footer: str = ""          # overflow note and feed link
    priority: str = "instant"
    include_summary: bool = True

    def text(self) -> str:
        """Plain-text rendering shared by channels without rich formatting."""
        lines = [self.header]
        if self.body:
            lines.append(self.body)
        for it in self.items:
            lines.append(f"• {it['title']}" + (f" · {item_detail(it)}" if item_detail(it) else ""))
            lines.append(f"  {it['url']}")
            if self.include_summary and it.get("summary"):
                lines.append(f"  {it['summary']}")
        if self.footer:
            lines.append(self.footer)
        return "\n".join(lines)


@dataclass
class SendResult:
    ok: bool
    messages: int = 0
    item_ids: list = field(default_factory=list)
    error: str | None = None


def build_messages(items: list[dict], priority: str, fmt: dict, ctx: dict) -> list[Message]:
    """Group, split by max_items_per_message, cap at MAX_MESSAGES with an overflow note."""
    names = ctx.get("category_names", {})
    stamp = ctx["now"].strftime("%m/%d %H:%M").lstrip("0").replace("/0", "/")
    per_msg = max(1, int(fmt.get("max_items_per_message", 10)))
    label = PRIORITY_LABEL.get(priority, "새 딜")

    groups: dict[str, list] = {}
    if fmt.get("group_by_category", True):
        for it in items:
            groups.setdefault(it.get("category") or "", []).append(it)
    else:
        groups["*"] = list(items)

    chunks = []
    for cat, its in groups.items():
        name = "딜봇" if cat == "*" else names.get(cat, cat or "기타")
        parts = [its[i:i + per_msg] for i in range(0, len(its), per_msg)]
        for n, part in enumerate(parts, 1):
            page = f" ({n}/{len(parts)})" if len(parts) > 1 else ""
            chunks.append(Message(header=f"[{name}] {label} {len(its)}건{page} · {stamp}",
                                  items=part, priority=priority,
                                  include_summary=fmt.get("include_summary", True)))
    overflow = sum(len(m.items) for m in chunks[MAX_MESSAGES:])
    chunks = chunks[:MAX_MESSAGES]
    feed_url = fmt.get("feed_url") or ""
    for m in chunks:
        m.footer = f"피드 보기: {feed_url}" if feed_url else ""
    if overflow and chunks:
        chunks[-1].footer = f"외 {overflow}건, 피드에서 확인" + (f"\n{chunks[-1].footer}" if feed_url else "")
    return chunks


class Notifier:
    type = ""
    label = ""
    required_env: tuple[str, ...] = ()

    def __init__(self, channel: dict, fmt: dict, ctx: dict, dry_run: bool = False):
        self.channel = channel
        self.fmt = fmt
        self.ctx = ctx
        self.dry_run = dry_run

    # ---- helpers for plugins
    @staticmethod
    def env(name: str, default: str | None = None) -> str | None:
        return os.environ.get(name) or default

    def missing_env(self) -> list[str]:
        return [n for n in self.required_env if not os.environ.get(n)]

    @property
    def target(self) -> str:
        return (self.channel.get("target") or "").strip()

    # ---- plugin contract
    def render(self, msg: Message):
        raise NotImplementedError

    def deliver(self, payload) -> None:
        raise NotImplementedError

    def describe(self, payload) -> str:
        """Dry-run output for one payload."""
        if isinstance(payload, (dict, list)):
            return json.dumps(payload, ensure_ascii=False, indent=2)
        return str(payload)

    # ---- driver
    def send(self, items: list[dict], priority: str) -> SendResult:
        if not items:
            return SendResult(ok=True)
        return self._send_messages(build_messages(items, priority, self.fmt, self.ctx))

    def send_text(self, title: str, body: str) -> SendResult:
        feed_url = self.fmt.get("feed_url") or ""
        msg = Message(header=title, body=body, footer=f"피드 보기: {feed_url}" if feed_url else "")
        return self._send_messages([msg])

    def _send_messages(self, messages: list[Message]) -> SendResult:
        cid = self.channel.get("id", self.type)
        if self.dry_run:
            for i, m in enumerate(messages, 1):
                print(f"----- [{cid}:{self.type}] message {i}/{len(messages)} -----")
                print(self.describe(self.render(m)))
            return SendResult(ok=True, messages=len(messages),
                              item_ids=[it["id"] for m in messages for it in m.items if "id" in it])
        missing = self.missing_env()
        if missing:
            return SendResult(ok=False, error=f"환경변수 없음: {', '.join(missing)}")
        sent_ids, count = [], 0
        for m in messages:
            payload = self.render(m)
            for attempt in (1, 2):
                try:
                    self.deliver(payload)
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 2:
                        return SendResult(ok=False, messages=count, item_ids=sent_ids,
                                          error=str(e)[:300])
                    time.sleep(2)
            count += 1
            sent_ids.extend(it["id"] for it in m.items if "id" in it)
        return SendResult(ok=True, messages=count, item_ids=sent_ids)


def load_plugins() -> dict[str, type[Notifier]]:
    import importlib
    import pkgutil
    from pathlib import Path

    plugins: dict[str, type[Notifier]] = {}
    for mod in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if mod.name == "base":
            continue
        module = importlib.import_module(f"notifiers.{mod.name}")
        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, Notifier) and obj is not Notifier and obj.type:
                plugins[obj.type] = obj
    return plugins
