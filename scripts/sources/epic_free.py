"""Epic Games Store weekly free games (official storefront promotions endpoint).

Usage: python scripts/sources/epic_free.py [--category ID] > candidates.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common
from sources import candidate, category_for

API = ("https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"
       "?locale=ko&country=KR&allowCountries=KR")
STORE = "https://store.epicgames.com/ko/p/"


def _slug(el: dict) -> str | None:
    for group in ("catalogNs", None):
        mappings = (el.get(group) or {}).get("mappings") if group else el.get("offerMappings")
        for m in mappings or []:
            if m.get("pageSlug"):
                return m["pageSlug"]
    slug = el.get("productSlug") or el.get("urlSlug")
    return slug.split("/")[0] if slug else None


def _kst_date(iso: str | None, tz) -> str | None:
    dt = common.parse_dt(iso)
    return dt.astimezone(tz).date().isoformat() if dt else None


def fetch(config: dict, arg=None, since=None, category: str | None = None) -> list[dict]:
    category = category or category_for(config, "epic_free")
    tz = common.tz_for(config)
    data = json.loads(common.http_get(API).decode("utf-8"))
    elements = data["data"]["Catalog"]["searchStore"]["elements"]
    out = []
    for el in elements:
        offers = ((el.get("promotions") or {}).get("promotionalOffers") or [])
        current = [o for group in offers for o in group.get("promotionalOffers", [])]
        free_now = [o for o in current
                    if (o.get("discountSetting") or {}).get("discountPercentage") == 0]
        price = (el.get("price") or {}).get("totalPrice") or {}
        if not free_now or price.get("discountPrice") != 0:
            continue
        title = el.get("title") or ""
        if not title or "mystery" in title.lower():
            continue
        decimals = (price.get("currencyInfo") or {}).get("decimals", 0)
        original = price.get("originalPrice")
        original_krw = (int(original / (10 ** decimals))
                        if original and price.get("currencyCode") == "KRW" else None)
        slug = _slug(el)
        offer = free_now[0]
        ends = _kst_date(offer.get("endDate"), tz)
        until = f" (~{int(ends[5:7])}/{int(ends[8:10])})" if ends else ""
        out.append(candidate(
            category=category,
            title=f"에픽게임즈 무료: {title}",
            url=STORE + slug if slug else "https://store.epicgames.com/ko/free-games",
            source="epic_free",
            price_krw=0,
            original_price_krw=original_krw,
            discount_pct=100,
            starts=_kst_date(offer.get("startDate"), tz),
            ends=ends,
            summary=f"에픽게임즈 스토어 기간 한정 무료 배포{until}. 받아두면 영구 소장.",
        ))
    return out


def main() -> int:
    common.setup_io()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--category", help="category id (default: first enabled category using epic_free)")
    args = ap.parse_args()
    config = common.load_data("config", {})
    try:
        items = fetch(config, category=args.category)
    except Exception as e:  # noqa: BLE001 - report any failure as a source error
        print(f"epic_free: {e}", file=sys.stderr)
        return 1
    common.dump(items)
    return 0


if __name__ == "__main__":
    sys.exit(main())
