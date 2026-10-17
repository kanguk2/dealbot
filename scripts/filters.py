"""Apply per-category rules from config.json to new items (spec step 4).

Rules, in order:
  - exclude word in title/summary          -> drop
  - rss:* source and no keyword matches    -> drop (feeds carry every deal; keywords narrow them)
  - discount_pct < min_discount_pct        -> drop (unknown discount passes)
  - price_krw > max_price_krw              -> drop (unknown price passes)
  - ends before today                      -> drop

Usage: python scripts/filters.py [FILE ...]   (default stdin) -> kept items on stdout
"""
from __future__ import annotations

import argparse
import sys

import common


def _has_any(text: str, words: list[str]) -> str | None:
    low = text.lower()
    for w in words:
        if w and w.lower() in low:
            return w
    return None


def reason_to_drop(item: dict, cat: dict, today) -> str | None:
    text = f"{item.get('title') or ''} {item.get('summary') or ''}"
    hit = _has_any(text, cat.get("exclude") or [])
    if hit:
        return f"exclude word '{hit}'"
    if (item.get("source") or "").startswith("rss:") and cat.get("keywords") \
            and not _has_any(text, cat["keywords"]):
        return "no keyword match"
    min_pct = cat.get("min_discount_pct")
    if min_pct is not None and item.get("discount_pct") is not None \
            and item["discount_pct"] < min_pct:
        return f"discount {item['discount_pct']}% < {min_pct}%"
    max_price = cat.get("max_price_krw")
    if max_price is not None and item.get("price_krw") is not None \
            and item["price_krw"] > max_price:
        return f"price {item['price_krw']} > {max_price}"
    ends = common.parse_date(item.get("ends"))
    if ends and ends < today:
        return f"ended {ends}"
    return None


def apply(items: list[dict], config: dict, today) -> tuple[list[dict], list[tuple]]:
    cats = {c["id"]: c for c in config.get("categories", [])}
    kept, dropped = [], []
    for it in items:
        cat = cats.get(it.get("category"))
        why = "unknown category" if cat is None else reason_to_drop(it, cat, today)
        if why:
            dropped.append((it.get("title"), why))
        else:
            kept.append(it)
    return kept, dropped


def main() -> int:
    common.setup_io()
    ap = argparse.ArgumentParser(description="apply config filters")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()
    config = common.load_data("config", {})
    kept, dropped = apply(common.read_items(args.files), config, common.now(config).date())
    for title, why in dropped:
        print(f"filter: dropped {title!r}: {why}", file=sys.stderr)
    common.dump(kept)
    return 0


if __name__ == "__main__":
    sys.exit(main())
