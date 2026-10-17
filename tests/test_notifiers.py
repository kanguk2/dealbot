import json
import os
import unittest
from datetime import datetime
from unittest import mock

import helpers  # noqa: F401  (puts scripts/ on sys.path)

from notifiers.base import MAX_MESSAGES, build_messages, load_plugins, price_text
from notifiers.kakao import TEXT_LIMIT
from notifiers.telegram import esc

FMT = {"max_items_per_message": 10, "group_by_category": True, "include_summary": True,
       "feed_url": "https://kanguk2.github.io/dealbot/"}
CTX = {"now": datetime(2026, 10, 17, 9, 3), "category_names": {"points": "포인트·적립", "shop": "쇼핑"}}


def deals(n, category="points"):
    return [{"id": f"{category}{i}", "category": category, "title": f"딜 {i}번 적립 이벤트",
             "url": f"https://e.com/{i}", "source": "rss:ppomppu_coupon", "price_krw": None,
             "original_price_krw": None, "discount_pct": None, "ends": "2026-10-31",
             "summary": "요약"} for i in range(n)]


class MessageTest(unittest.TestCase):
    def test_split_and_cap(self):
        msgs = build_messages(deals(35), "instant", FMT, CTX)
        self.assertEqual(len(msgs), MAX_MESSAGES)
        self.assertEqual([len(m.items) for m in msgs], [10, 10, 10])
        self.assertIn("외 5건, 피드에서 확인", msgs[-1].footer)
        self.assertEqual(msgs[0].header, "[포인트·적립] 새 딜 35건 (1/4) · 10/17 09:03")

    def test_group_by_category(self):
        msgs = build_messages(deals(2) + deals(1, "shop"), "daily", FMT, CTX)
        self.assertEqual([m.header.split("]")[0] for m in msgs], ["[포인트·적립", "[쇼핑"])
        self.assertIn("어제 모은 딜", msgs[0].header)
        merged = build_messages(deals(2) + deals(1, "shop"), "daily", {**FMT, "group_by_category": False}, CTX)
        self.assertEqual(len(merged), 1)

    def test_price_text(self):
        self.assertEqual(price_text({"price_krw": 0, "original_price_krw": 32000}), "무료 (정가 32,000원)")
        self.assertEqual(price_text({"price_krw": 12900, "discount_pct": 35, "original_price_krw": 20000}),
                         "12,900원 -35% 정가 20,000원")
        self.assertIsNone(price_text({}))


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.plugins = load_plugins()

    def make(self, type_, target="", dry_run=False):
        return self.plugins[type_]({"id": type_, "type": type_, "target": target}, FMT, CTX, dry_run=dry_run)

    def test_all_seven_channels_registered(self):
        self.assertEqual(sorted(self.plugins),
                         ["discord", "email", "kakao", "ntfy", "pushover", "slack", "telegram"])

    def test_every_channel_shows_overflow_note(self):
        last = build_messages(deals(35), "instant", FMT, CTX)[-1]
        for type_, cls in self.plugins.items():
            payload = json.dumps(self.make(type_, "t").render(last), ensure_ascii=False)
            self.assertIn("외 5건", payload.replace("\\", ""), type_)

    def test_kakao_text_limit_keeps_overflow(self):
        last = build_messages(deals(35), "instant", FMT, CTX)[-1]
        text = self.make("kakao").render(last)["text"]
        self.assertLessEqual(len(text), TEXT_LIMIT)
        self.assertTrue(text.endswith("외 5건, 피드에서 확인"))

    def test_telegram_escaping(self):
        self.assertEqual(esc("[a] b.c-d!"), r"\[a\] b\.c\-d\!")

    def test_env_overrides_public_target(self):
        with mock.patch.dict(os.environ, {"DEALBOT_NTFY_TOPIC": "secret-topic"}):
            self.assertEqual(self.make("ntfy", "public").render(build_messages(deals(1), "instant", FMT, CTX)[0])["topic"],
                             "secret-topic")

    def test_missing_env_is_reported_without_network(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            res = self.make("slack").send(deals(1), "instant")
        self.assertFalse(res.ok)
        self.assertIn("DEALBOT_SLACK_WEBHOOK", res.error)

    def test_retry_once_then_error(self):
        n = self.make("ntfy", "t")
        with mock.patch.object(type(n), "deliver", side_effect=RuntimeError("boom")) as d, \
                mock.patch("notifiers.base.time.sleep"):
            res = n.send(deals(1), "instant")
        self.assertEqual(d.call_count, 2)
        self.assertFalse(res.ok)

    def test_retry_succeeds(self):
        n = self.make("ntfy", "t")
        with mock.patch.object(type(n), "deliver", side_effect=[RuntimeError("x"), None]), \
                mock.patch("notifiers.base.time.sleep"):
            res = n.send(deals(3), "instant")
        self.assertTrue(res.ok)
        self.assertEqual(res.item_ids, ["points0", "points1", "points2"])


if __name__ == "__main__":
    unittest.main()
