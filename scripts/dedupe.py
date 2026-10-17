"""Candidates -> new items only.

Normalizes candidates into feed-item shape, assigns ``key`` (normalized title + price)
and ``id``, and drops anything already in data/seen.json or repeated within the batch.

Usage:
  python scripts/dedupe.py [FILE ...]          # FILE defaults to stdin ('-')
  python scripts/dedupe.py cand.json --write   # also record keys in seen.json and prune expired
Output: JSON array of new items on stdout. Rejected candidates are reported on stderr.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import timedelta

import common

FIELDS = ("category", "title", "url", "source", "price_krw", "original_price_krw",
          "discount_pct", "starts", "ends", "summary")
NORM_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize_title(title: str) -> str:
    return NORM_RE.sub("", title.lower())


def make_key(item: dict) -> str:
    price = "" if item.get("price_krw") is None else str(item["price_krw"])
    return f"{item['category']}|{normalize_title(item['title'])}|{price}"


def make_id(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _int_or_none(v):
    if v is None or v == "":
        return None
    try:
        return int(round(float(str(v).replace(",", ""))))
    except ValueError:
        return None


def clean(raw: dict, categories: set[str]) -> tuple[dict | None, str | None]:
    """Coerce one candidate. Returns (item, None) or (None, reason)."""
    item = {f: raw.get(f) for f in FIELDS}
    title = (item["title"] or "").strip()
    url = (item["url"] or "").strip()
    if not title:
        return None, "title missing"
    if not url.startswith(("http://", "https://")):
        return None, f"bad url: {url!r}"
    if item["category"] not in categories:
        return None, f"unknown or disabled category: {item['category']!r}"
    item["title"], item["url"] = title, url
    item["source"] = item["source"] or "search"
    for f in ("price_krw", "original_price_krw", "discount_pct"):
        item[f] = _int_or_none(item[f])
    for f in ("starts", "ends"):
        d = common.parse_date(item[f]) if isinstance(item[f], str) else None
        item[f] = d.isoformat() if d else None
    p, o = item["price_krw"], item["original_price_krw"]
    if item["discount_pct"] is None and p is not None and o and o > p:
        item["discount_pct"] = round((o - p) * 100 / o)
    if item["discount_pct"] is not None:
        item["discount_pct"] = max(0, min(100, item["discount_pct"]))
    item["summary"] = (item["summary"] or "").strip() or None
    return item, None


def dedupe(candidates: list[dict], config: dict, seen: dict) -> tuple[list[dict], list[tuple]]:
    categories = {c["id"] for c in config.get("categories", []) if c.get("enabled")}
    known = set((seen.get("keys") or {}).keys())
    new, rejected = [], []
    for raw in candidates:
        item, reason = clean(raw, categories)
        if item is None:
            rejected.append((raw.get("title"), reason))
            continue
        key = make_key(item)
        if key in known:
            continue
        known.add(key)
        new.append({"id": make_id(key), "key": key, **item})
    return new, rejected


def prune(seen: dict, ttl_days: int, today) -> int:
    keys = seen.setdefault("keys", {})
    cutoff = today - timedelta(days=ttl_days)
    expired = [k for k, d in keys.items() if (common.parse_date(d) or today) < cutoff]
    for k in expired:
        del keys[k]
    return len(expired)


def remember(seen: dict, items: list[dict], today) -> None:
    keys = seen.setdefault("keys", {})
    for it in items:
        keys[it["key"]] = today.isoformat()


def main() -> int:
    common.setup_io()
    ap = argparse.ArgumentParser(description="candidates -> new items")
    ap.add_argument("files", nargs="*", help="candidate JSON files (default: stdin)")
    ap.add_argument("--write", action="store_true", help="update data/seen.json")
    args = ap.parse_args()

    config = common.load_data("config", {})
    seen = common.load_data("seen", {"keys": {}})
    today = common.now(config).date()
    prune(seen, config.get("seen_ttl_days", 30), today)

    new, rejected = dedupe(common.read_items(args.files), config, seen)
    for title, reason in rejected:
        print(f"dedupe: skipped {title!r}: {reason}", file=sys.stderr)
    if args.write:
        remember(seen, new, today)
        common.save_data("seen", seen)
    common.dump(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
