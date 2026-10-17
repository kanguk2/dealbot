"""feed.recent pool, interests.json / links.json validation and interest findings in review_run."""
import json
import unittest

from helpers import DataDirTest, item

DAY1 = "2026-10-17T09:00:00+09:00"
DAY1_EVE = "2026-10-17T19:00:00+09:00"
DAY2 = "2026-10-18T09:00:00+09:00"
DAY4 = "2026-10-20T09:00:00+09:00"


def titles(items):
    return [i["title"] for i in items]


class RecentPoolTest(DataDirTest):
    def test_recent_keeps_earlier_runs_newest_first(self):
        self.collect([item(1), item(2)], DAY1)
        self.collect([item(3)], DAY1_EVE)
        feed = self.read("feed")
        self.assertEqual(titles(feed["items"]), ["테스트 적립 이벤트 3"])
        self.assertEqual(titles(feed["recent"]), ["테스트 적립 이벤트 3", "테스트 적립 이벤트 1", "테스트 적립 이벤트 2"])
        self.assert_valid()

    def test_empty_run_keeps_the_pool(self):
        self.collect([item(1)], DAY1)
        self.collect([], DAY1_EVE)
        feed = self.read("feed")
        self.assertEqual(feed["items"], [])
        self.assertEqual(titles(feed["recent"]), ["테스트 적립 이벤트 1"])

    def test_expired_items_leave_the_pool(self):
        self.collect([item(1, ends="2026-10-18"), item(2, ends="2026-10-25"), item(3)], DAY1)
        self.collect([], DAY2)  # ends == today: still open
        self.assertEqual(len(self.read("feed")["recent"]), 3)
        self.collect([], DAY4)  # 10-18 < 10-20: dropped
        self.assertEqual(titles(self.read("feed")["recent"]), ["테스트 적립 이벤트 2", "테스트 적립 이벤트 3"])
        self.assert_valid()

    def test_page_marks_are_carried_into_the_pool(self):
        self.collect([item(1), item(2)], DAY1)
        self.edit("feed", lambda f: f["items"][0].update(status="bought"))
        self.collect([item(3)], DAY1_EVE)
        status = {i["title"]: i["status"] for i in self.read("feed")["recent"]}
        self.assertEqual(status, {"테스트 적립 이벤트 1": "bought", "테스트 적립 이벤트 2": "new",
                                  "테스트 적립 이벤트 3": "new"})

    def test_ignored_on_the_page_leaves_the_pool(self):
        self.collect([item(1), item(2)], DAY1)
        self.edit("feed", lambda f: f["items"][1].update(status="ignored"))
        self.collect([item(3)], DAY1_EVE)
        recent = self.read("feed")["recent"]
        self.assertNotIn("테스트 적립 이벤트 2", titles(recent),
                         f"ignored deal still in the pool: {[(i['title'], i['status']) for i in recent]}")

    def test_ignored_pool_item_is_dropped_on_the_next_run(self):
        self.collect([item(1), item(2)], DAY1)
        self.edit("feed", lambda f: f["recent"][1].update(status="ignored"))
        self.collect([], DAY1_EVE)
        self.assertEqual(titles(self.read("feed")["recent"]), ["테스트 적립 이벤트 1"])

    def test_pool_is_capped_at_60_newest_first(self):
        self.collect([item(n) for n in range(1, 51)], DAY1)
        self.collect([item(n) for n in range(51, 71)], DAY1_EVE)
        recent = self.read("feed")["recent"]
        self.assertEqual(len(recent), 60)
        self.assertEqual(recent[0]["title"], "테스트 적립 이벤트 51")
        self.assertEqual(recent[19]["title"], "테스트 적립 이벤트 70")
        self.assertEqual(recent[20]["title"], "테스트 적립 이벤트 1")
        self.assertNotIn("테스트 적립 이벤트 41", titles(recent))
        self.assert_valid()

    def test_one_run_with_more_than_60_new_items_is_capped(self):
        self.collect([item(n) for n in range(1, 71)], DAY1)
        feed = self.read("feed")
        self.assertEqual((len(feed["items"]), len(feed["recent"])), (70, 60))
        self.assert_valid()

    def test_pool_is_deduped_by_id(self):
        self.collect([item(1), item(2)], DAY1)
        self.edit("feed", lambda f: f.update(recent=f["recent"] + [dict(f["recent"][0], title="중복 복사본")]))
        self.collect([], DAY1_EVE)
        recent = self.read("feed")["recent"]
        self.assertEqual(len({i["id"] for i in recent}), len(recent))
        self.assertEqual(titles(recent), ["테스트 적립 이벤트 1", "테스트 적립 이벤트 2"])

    def test_feed_without_recent_is_migrated(self):
        self.write("feed", {"run_at": None, "items": [], "pending": [], "bought": []})
        self.collect([item(1)], DAY1)
        self.assertEqual(titles(self.read("feed")["recent"]), ["테스트 적립 이벤트 1"])
        self.assert_valid()


class InterestReviewTest(DataDirTest):
    def review(self):
        return json.loads(self.run_script("review_run.py").stdout)

    def kinds(self, report):
        return {f["type"]: f for f in report["findings"]}

    def test_matching_new_deal_is_an_interest_hit(self):
        self.write("interests", {"terms": ["네이버"], "saved": []})
        self.collect([item(1, title="네이버페이 적립 이벤트"), item(2)], DAY1)
        found = self.kinds(self.review())
        self.assertIn("interest_hits", found)
        self.assertNotIn("interest_miss", found)
        self.assertEqual(found["interest_hits"]["evidence"], ["네이버페이 적립 이벤트"])

    def test_summary_match_counts_and_case_is_ignored(self):
        self.write("interests", {"terms": ["KB"], "saved": []})
        self.collect([item(1, summary="kb pay 결제 시 적립")], DAY1)
        self.assertIn("interest_hits", self.kinds(self.review()))

    def test_no_matching_deal_is_an_interest_miss(self):
        self.write("interests", {"terms": ["카카오"], "saved": []})
        self.collect([item(1)], DAY1)
        found = self.kinds(self.review())
        self.assertIn("interest_miss", found)
        self.assertNotIn("interest_hits", found)

    def test_no_terms_means_no_interest_findings(self):
        self.collect([item(1)], DAY1)
        found = self.kinds(self.review())
        self.assertNotIn("interest_hits", found)
        self.assertNotIn("interest_miss", found)

    def test_missing_interests_file_does_not_crash_review(self):
        (self.data / "interests.json").unlink()
        self.collect([item(1)], DAY1)
        self.assertNotIn("interest_miss", self.kinds(self.review()))


class InterestsLinksValidateTest(DataDirTest):
    def assert_invalid(self, needle):
        out = self.run_script("validate.py", check=False)
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertIn(needle, out.stdout)

    def test_31_interest_terms_fail_validation(self):
        self.write("interests", {"terms": [f"t{n}" for n in range(31)], "saved": []})
        self.assert_invalid("interests")

    def test_30_interest_terms_and_a_saved_deal_are_valid(self):
        self.write("interests", {"terms": [f"t{n}" for n in range(30)], "saved": [
            {"id": "a1", "title": "x", "url": "https://e.com", "source": "search", "category": "points",
             "saved_at": "2026-10-17"}]})
        self.assert_valid()

    def test_saved_deal_without_saved_at_fails_validation(self):
        self.write("interests", {"terms": [], "saved": [
            {"id": "a1", "title": "x", "url": "https://e.com", "source": "search", "category": "points"}]})
        self.assert_invalid("interests")

    def test_http_link_fails_validation(self):
        self.edit("links", lambda d: d["groups"][0]["links"][0].update(url="http://example.com/"))
        self.assert_invalid("links")

    def test_missing_interests_file_is_reported(self):
        (self.data / "interests.json").unlink()
        self.assert_invalid("interests: missing file")

    def test_recent_over_60_fails_validation(self):
        self.collect([item(1)], DAY1)
        self.edit("feed", lambda f: f.update(recent=[dict(f["recent"][0], id=f"x{n}") for n in range(61)]))
        self.assert_invalid("recent")


if __name__ == "__main__":
    unittest.main()
