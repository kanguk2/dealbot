"""Generic RSS 2.0 / Atom reader for the feeds listed in config.rss_feeds.

Usage: python scripts/sources/rss.py [FEED_ID ...] [--all]
  FEED_ID  key of config.rss_feeds (default: every feed used by an enabled category)
  --all    include entries older than the last run in data/runs.json
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common
from sources import candidate, category_for

ATOM = "{http://www.w3.org/2005/Atom}"
PRICE_RE = re.compile(r"(?:[￦₩]\s*([\d,]{3,})|([\d,]{3,})\s*원)")
# Only explicit discounts: "-85%", "30% 할인", "20%off". A bare "100% 당첨" is not a discount.
PCT_RE = re.compile(r"-\s*(\d{1,3})\s*%|(\d{1,3})\s*%\s*(?:할인|off|세일|dc)", re.I)
TAG_RE = re.compile(r"<[^>]+>")
URL_RE = re.compile(r"https?://\S+")
DECL_RE = re.compile(rb"^\s*<\?xml[^>]*encoding=[\"']([\w.-]+)[\"'][^>]*\?>", re.I)


def _parse_xml(raw: bytes) -> ET.Element:
    # expat cannot decode multi-byte legacy encodings (e.g. EUC-KR); decode in Python.
    m = DECL_RE.match(raw)
    encoding = m.group(1).decode() if m else "utf-8"
    text = raw[m.end():] if m else raw
    return ET.fromstring(text.decode(encoding, "replace").lstrip("﻿"))


def _text(el, *names) -> str:
    for n in names:
        found = el.find(n)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _clean(s: str, limit: int) -> str:
    s = html.unescape(TAG_RE.sub(" ", html.unescape(s)))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _published(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return common.parse_dt(s)


def _price(title: str) -> int | None:
    m = PRICE_RE.search(title)
    if not m:
        return None
    digits = (m.group(1) or m.group(2)).replace(",", "")
    return int(digits) if digits.isdigit() else None


def _pct(title: str) -> int | None:
    for m in PCT_RE.finditer(title):
        v = int(m.group(1) or m.group(2))
        if 0 < v <= 100:
            return v
    return None


def entries(raw: bytes) -> list[dict]:
    root = _parse_xml(raw)
    out = []
    for it in root.iter("item"):  # RSS 2.0
        out.append({"title": _text(it, "title"), "link": _text(it, "link", "guid"),
                    "date": _text(it, "pubDate", "{http://purl.org/dc/elements/1.1/}date"),
                    "summary": _text(it, "description")})
    for it in root.iter(f"{ATOM}entry"):  # Atom
        link = it.find(f"{ATOM}link")
        out.append({"title": _text(it, f"{ATOM}title"),
                    "link": link.get("href", "") if link is not None else "",
                    "date": _text(it, f"{ATOM}published", f"{ATOM}updated"),
                    "summary": _text(it, f"{ATOM}summary", f"{ATOM}content")})
    return out


def fetch(config: dict, arg=None, since=None) -> list[dict]:
    feed_id = arg
    url = (config.get("rss_feeds") or {}).get(feed_id)
    if not url:
        raise ValueError(f"rss feed '{feed_id}' is not in config.rss_feeds")
    source = f"rss:{feed_id}"
    category = category_for(config, source)
    tz = common.tz_for(config)
    out = []
    for e in entries(common.http_get(url)):
        title = _clean(e["title"], 200)
        if not title or not e["link"].startswith("http"):
            continue
        published = _published(e["date"])
        if since and published and published <= since:
            continue
        out.append(candidate(
            category=category, title=title, url=e["link"].strip(), source=source,
            price_krw=_price(title), discount_pct=_pct(title),
            starts=published.astimezone(tz).date().isoformat() if published else None,
            summary=_clean(URL_RE.sub(" ", _clean(e["summary"], 5000)), 140) or None,
        ))
    return out


def main() -> int:
    common.setup_io()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("feed_ids", nargs="*")
    ap.add_argument("--all", action="store_true", help="ignore last-run cutoff")
    args = ap.parse_args()
    config = common.load_data("config", {})
    since = None if args.all else common.last_run_at(common.load_data("runs", {}))
    feed_ids = args.feed_ids or [
        s.split(":", 1)[1] for c in config.get("categories", []) if c.get("enabled")
        for s in c.get("sources", []) if s.startswith("rss:")]
    items, failed = [], 0
    for fid in dict.fromkeys(feed_ids):
        try:
            items.extend(fetch(config, fid, since=since))
        except Exception as e:  # noqa: BLE001
            print(f"rss:{fid}: {e}", file=sys.stderr)
            failed += 1
    common.dump(items)
    return 1 if failed and not items else 0


if __name__ == "__main__":
    sys.exit(main())
