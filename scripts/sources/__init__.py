"""Deterministic source adapters.

Each adapter exposes ``fetch(config, arg=None, since=None) -> list[dict]`` returning
candidates in feed-item shape (title, url, source, category, prices, dates, summary).
Unknown values stay ``None``. ``dedupe.py`` fills in ``key`` / ``id``.

Source ids in config.json:
  epic_free        -> sources/epic_free.py
  rss:<feed_id>    -> sources/rss.py with config.rss_feeds[feed_id]
  search           -> not a script; Codex does the web search itself
"""
from __future__ import annotations

import importlib

NON_SCRIPT_SOURCES = {"search"}


def category_for(config: dict, source_id: str) -> str | None:
    """First enabled category that lists this source."""
    for cat in config.get("categories", []):
        if cat.get("enabled") and source_id in cat.get("sources", []):
            return cat["id"]
    return None


def enabled_sources(config: dict) -> list[str]:
    """Script-backed source ids used by enabled categories, in config order."""
    out: list[str] = []
    for cat in config.get("categories", []):
        if not cat.get("enabled"):
            continue
        for src in cat.get("sources", []):
            if src not in NON_SCRIPT_SOURCES and src not in out:
                out.append(src)
    return out


def fetch_source(config: dict, source_id: str, since=None) -> list[dict]:
    name, _, arg = source_id.partition(":")
    try:
        module = importlib.import_module(f"sources.{name}")
    except ModuleNotFoundError:
        raise ValueError(f"unknown source '{source_id}'") from None
    return module.fetch(config, arg or None, since=since)


def candidate(**fields) -> dict:
    base = {
        "category": None, "title": None, "url": None, "source": None,
        "price_krw": None, "original_price_krw": None, "discount_pct": None,
        "starts": None, "ends": None, "summary": None,
    }
    base.update(fields)
    return base
