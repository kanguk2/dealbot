import unittest
from datetime import date

from helpers import item

import dedupe
import filters

CONFIG = {
    "categories": [
        {"id": "points", "name": "포인트", "enabled": True, "keywords": ["적립", "캐시백"],
         "exclude": ["광고"], "sources": ["search", "rss:x"], "min_discount_pct": 30,
         "max_price_krw": 50000, "priority": "daily"},
        {"id": "off", "name": "꺼짐", "enabled": False, "keywords": ["x"], "exclude": [],
         "sources": ["search"], "priority": "instant"},
    ],
    "min_days_left": 0,
}
TODAY = date(2026, 10, 17)


class DedupeTest(unittest.TestCase):
    def test_key_normalizes_title_and_price(self):
        a = dedupe.make_key({"category": "points", "title": "Ghost Runner!! 무료", "price_krw": 0})
        b = dedupe.make_key({"category": "points", "title": "ghostrunner 무료", "price_krw": 0})
        self.assertEqual(a, b)
        self.assertEqual(a, "points|ghostrunner무료|0")
        self.assertNotEqual(a, dedupe.make_key({"category": "points", "title": "ghostrunner 무료", "price_krw": 1}))

    def test_drops_seen_and_batch_duplicates(self):
        seen = {"keys": {dedupe.make_key(item(1)): "2026-10-16"}}
        new, rejected = dedupe.dedupe([item(1), item(2), item(2, url="https://other.example/2")], CONFIG, seen)
        self.assertEqual([n["title"] for n in new], ["테스트 적립 이벤트 2"])
        self.assertEqual(rejected, [])
        self.assertTrue(new[0]["id"] and new[0]["key"])

    def test_rejects_invalid_candidates(self):
        bad = [item(1, title=""), item(2, url="ftp://x"), item(3, category="off"), item(4, category="nope")]
        new, rejected = dedupe.dedupe(bad, CONFIG, {"keys": {}})
        self.assertEqual(new, [])
        self.assertEqual(len(rejected), 4)
        self.assertIn("title missing", rejected[0][1])
        self.assertIn("bad url", rejected[1][1])

    def test_coerces_values_and_computes_discount(self):
        new, _ = dedupe.dedupe([item(1, price_krw="12,900", original_price_krw=20000, ends="2026-10-31T00:00:00")],
                               CONFIG, {"keys": {}})
        it = new[0]
        self.assertEqual(it["price_krw"], 12900)
        self.assertEqual(it["discount_pct"], 36)
        self.assertEqual(it["ends"], "2026-10-31")

    def test_never_invents_values(self):
        new, _ = dedupe.dedupe([item(1, price_krw=None, ends="언젠가")], CONFIG, {"keys": {}})
        self.assertIsNone(new[0]["price_krw"])
        self.assertIsNone(new[0]["discount_pct"])
        self.assertIsNone(new[0]["ends"])

    def test_prune_expires_old_keys(self):
        seen = {"keys": {"old": "2026-09-01", "fresh": "2026-10-10"}}
        self.assertEqual(dedupe.prune(seen, 30, TODAY), 1)
        self.assertEqual(list(seen["keys"]), ["fresh"])


class FilterTest(unittest.TestCase):
    def reasons(self, *items, min_days=0, today=TODAY):
        cfg = {**CONFIG, "min_days_left": min_days}
        kept, dropped = filters.apply([dict(i, id=str(n)) for n, i in enumerate(items)], cfg, today)
        return [it["title"] for it in kept], [why for _, why in dropped]

    def test_exclude_word(self):
        kept, why = self.reasons(item(1, title="광고 적립 이벤트"))
        self.assertEqual(kept, [])
        self.assertIn("exclude", why[0])

    def test_rss_needs_keyword_but_search_does_not(self):
        kept, why = self.reasons(item(1, title="그냥 퀴즈", source="rss:x"), item(2, title="그냥 퀴즈 2"))
        self.assertEqual(kept, ["그냥 퀴즈 2"])
        self.assertIn("no keyword", why[0])

    def test_rss_all_category_keeps_rss_items_without_keywords(self):
        cfg = {**CONFIG, "categories": [dict(CONFIG["categories"][0], rss_all=True)]}
        kept, dropped = filters.apply([dict(item(1, title="그냥 핫딜 노트북", source="rss:x"), id="a"),
                                       dict(item(2, title="광고 핫딜", source="rss:x"), id="b")], cfg, TODAY)
        self.assertEqual([k["title"] for k in kept], ["그냥 핫딜 노트북"])
        self.assertIn("exclude", dropped[0][1])  # rss_all skips keywords only, not exclude words

    def test_rss_all_false_still_needs_a_keyword(self):
        cfg = {**CONFIG, "categories": [dict(CONFIG["categories"][0], rss_all=False)]}
        kept, dropped = filters.apply([dict(item(1, title="그냥 핫딜", source="rss:x"), id="a")], cfg, TODAY)
        self.assertEqual(kept, [])
        self.assertIn("no keyword", dropped[0][1])

    def test_rss_all_still_applies_discount_and_end_date_limits(self):
        cfg = {**CONFIG, "categories": [dict(CONFIG["categories"][0], rss_all=True)]}
        kept, dropped = filters.apply([dict(item(1, title="핫딜", source="rss:x", discount_pct=5), id="a"),
                                       dict(item(2, title="핫딜2", source="rss:x", ends="2026-10-16"), id="b")],
                                      cfg, TODAY)
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 2)

    def test_discount_and_price_limits_unknown_passes(self):
        kept, why = self.reasons(item(1, discount_pct=10), item(2, price_krw=60000),
                                 item(3, discount_pct=None, price_krw=None))
        self.assertEqual(kept, ["테스트 적립 이벤트 3"])
        self.assertEqual(len(why), 2)

    def test_expired_is_always_dropped(self):
        kept, why = self.reasons(item(1, ends="2026-10-16"), item(2, ends="2026-10-17"))
        self.assertEqual(kept, ["테스트 적립 이벤트 2"])
        self.assertIn("ended", why[0])

    def test_min_days_left(self):
        items = [item(1, ends="2026-10-17"), item(2, ends="2026-10-19"), item(3, ends="2026-10-20"),
                 item(4, ends=None)]
        kept, why = self.reasons(*items, min_days=3)
        self.assertEqual(kept, ["테스트 적립 이벤트 3", "테스트 적립 이벤트 4"])
        self.assertTrue(all("less than 3 days" in w for w in why))


if __name__ == "__main__":
    unittest.main()
