import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from helpers import FIXTURES

import common
from sources import category_for, enabled_sources, epic_free, rss

CONFIG = {
    "schedule": {"timezone": "Asia/Seoul"},
    "categories": [
        {"id": "points", "enabled": True, "sources": ["rss:feed", "search", "epic_free"]},
        {"id": "off", "enabled": False, "sources": ["rss:other"]},
    ],
    "rss_feeds": {"feed": "https://feed.example/rss", "other": "https://other.example/rss"},
}
KST = timezone(timedelta(hours=9))


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class RegistryTest(unittest.TestCase):
    def test_enabled_sources_skip_search_and_disabled(self):
        self.assertEqual(enabled_sources(CONFIG), ["rss:feed", "epic_free"])
        self.assertEqual(category_for(CONFIG, "rss:feed"), "points")
        self.assertIsNone(category_for(CONFIG, "rss:other"))


class RssTest(unittest.TestCase):
    def fetch(self, name: str, since=None):
        with mock.patch.object(common, "http_get", return_value=fixture(name)):
            return rss.fetch(CONFIG, "feed", since=since)

    def test_utf8_and_euckr_parse_the_same(self):
        a, b = self.fetch("rss_utf8.xml"), self.fetch("rss_euckr.xml")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 3)

    def test_fields(self):
        first = self.fetch("rss_utf8.xml")[0]
        self.assertEqual(first["category"], "points")
        self.assertEqual(first["source"], "rss:feed")
        self.assertEqual(first["price_krw"], 1260630)
        self.assertEqual(first["discount_pct"], 20)
        self.assertEqual(first["starts"], "2026-10-17")
        self.assertEqual(first["summary"], "본문 요약")  # tags and URLs stripped

    def test_bare_percent_is_not_a_discount(self):
        self.assertIsNone(self.fetch("rss_utf8.xml")[1]["discount_pct"])

    def test_won_sign_price(self):
        self.assertEqual(self.fetch("rss_utf8.xml")[2]["price_krw"], 7920)

    def test_since_cutoff(self):
        items = self.fetch("rss_utf8.xml", since=datetime(2026, 10, 16, 0, 0, tzinfo=KST))
        self.assertEqual(len(items), 2)

    def test_atom(self):
        items = self.fetch("atom.xml")
        self.assertEqual(items[0]["url"], "https://example.com/a1")
        self.assertEqual(items[0]["discount_pct"], 30)

    def test_unknown_feed_raises(self):
        with self.assertRaises(ValueError):
            rss.fetch(CONFIG, "missing")


class EpicTest(unittest.TestCase):
    def test_only_current_free_games(self):
        with mock.patch.object(common, "http_get", return_value=fixture("epic.json")):
            items = epic_free.fetch(CONFIG)
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["title"], "에픽게임즈 무료: Free Game")
        self.assertEqual(it["url"], "https://store.epicgames.com/ko/p/free-game-123")
        self.assertEqual((it["price_krw"], it["original_price_krw"], it["discount_pct"]), (0, 13300, 100))
        self.assertEqual((it["starts"], it["ends"]), ("2026-10-16", "2026-10-23"))  # KST dates
        self.assertEqual(it["category"], "points")


if __name__ == "__main__":
    unittest.main()
