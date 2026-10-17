"""End-to-end runs of the CLI scripts against a scratch data dir (no network)."""
import json
import unittest

from helpers import DataDirTest, item

DAY1 = "2026-10-17T09:00:00+09:00"  # Saturday
DAY1_EVE = "2026-10-17T19:00:00+09:00"
DAY2 = "2026-10-18T09:00:00+09:00"
NTFY = {"DEALBOT_NTFY_TOPIC": "test-topic"}


class FeedReplaceTest(DataDirTest):
    def test_each_run_replaces_the_page(self):
        run = self.collect([item(1), item(2)], DAY1)
        self.assertEqual((run["found"], run["new"]), (2, 2))
        feed = self.read("feed")
        self.assertEqual(len(feed["items"]), 2)
        self.assertEqual(feed["run_at"], DAY1)

        self.collect([item(1), item(3)], DAY1_EVE)  # item 1 already seen
        feed = self.read("feed")
        self.assertEqual([i["title"] for i in feed["items"]], ["테스트 적립 이벤트 3"])
        self.assertEqual(self.read("runs")["runs"][0]["dropped"], {"already_seen": 1})
        self.assert_valid()

    def test_empty_run_empties_the_page(self):
        self.collect([item(1)], DAY1)
        self.collect([], DAY1_EVE)
        feed = self.read("feed")
        self.assertEqual(feed["items"], [])
        self.assertEqual(feed["run_at"], DAY1_EVE)
        self.assert_valid()

    def test_expired_and_too_close_never_reach_the_page(self):
        self.edit("config", lambda c: c.update(min_days_left=2))
        run = self.collect([item(1, ends="2026-10-16"), item(2, ends="2026-10-18"),
                            item(3, ends="2026-10-19"), item(4)], DAY1)
        titles = [i["title"] for i in self.read("feed")["items"]]
        self.assertEqual(titles, ["테스트 적립 이벤트 3", "테스트 적립 이벤트 4"])
        self.assertEqual(run["dropped"], {"ended": 1, "too_close": 1})

    def test_user_marks_become_feedback_and_bought_is_kept(self):
        self.collect([item(1), item(2)], DAY1)

        def mark(feed):
            feed["items"][0]["status"] = "bought"
            feed["items"][1]["status"] = "ignored"
        self.edit("feed", mark)
        run = self.collect([item(3)], DAY1_EVE)
        self.assertEqual(len(run["user_feedback"]["bought"]), 1)
        self.assertEqual(len(run["user_feedback"]["ignored"]), 1)
        feed = self.read("feed")
        self.assertEqual(len(feed["bought"]), 1)
        self.assertEqual(feed["bought"][0]["status"], "bought")
        self.assert_valid()

    def test_bad_search_file_is_a_source_error_not_a_crash(self):
        bad = self.tmp / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        self.run_script("run_deterministic.py", "--no-sources", "--extra", str(bad),
                        "--source-error", "search=blocked", now=DAY1)
        errors = self.read("runs")["runs"][0]["errors"]
        self.assertEqual([e["source"] for e in errors], ["search", "search"])

    def test_old_feed_format_is_migrated(self):
        self.write("feed", {"items": []})
        self.collect([item(1)], DAY1)
        self.assertEqual(set(self.read("feed")), {"run_at", "items", "pending", "bought"})


class NotifyScheduleTest(DataDirTest):
    """Default config: points is 'daily', ntfy takes instant+daily."""

    def notify(self, now, *extra, env=NTFY):
        return self.run_script("notify.py", "--since-run", *extra, now=now, env=env).stdout

    def test_daily_digest_survives_feed_replacement(self):
        self.collect([item(1), item(2)], DAY1)
        self.assertIn("0 items sent", self.notify("2026-10-17T09:01:00+09:00", "--dry-run"))
        self.collect([], DAY1_EVE)                       # page emptied
        self.assertEqual(len(self.read("feed")["pending"]), 2)
        out = self.notify("2026-10-18T09:01:00+09:00", "--dry-run")
        self.assertIn("ntfy daily: 2/2 items", out)

    def test_sent_items_leave_the_queue_and_are_not_resent(self):
        self.collect([item(1)], DAY1)
        self.collect([], DAY2)
        with self.fake_ntfy() as sent:
            self.notify("2026-10-18T09:01:00+09:00")
            self.notify("2026-10-18T09:05:00+09:00")
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.read("feed")["pending"], [])
        self.assertEqual(self.read("runs")["runs"][0]["notified"], 1)
        self.assert_valid()

    def test_failed_channel_retries_next_run(self):
        self.collect([item(1)], DAY1)
        self.collect([], DAY2)
        self.notify("2026-10-18T09:01:00+09:00", env={})  # no topic -> error
        runs = self.read("runs")["runs"]
        self.assertEqual(runs[0]["errors"][0]["source"], "notify:ntfy")
        self.assertEqual(len(self.read("feed")["pending"]), 1)
        out = self.notify("2026-10-18T19:01:00+09:00", "--dry-run")
        self.assertIn("ntfy daily: 1/1 items", out)

    def test_ignored_items_are_not_sent(self):
        self.collect([item(1), item(2)], DAY1)
        self.edit("feed", lambda f: f["items"][0].update(status="ignored"))
        out = self.notify("2026-10-18T09:01:00+09:00", "--dry-run")
        self.assertIn("ntfy daily: 1/1 items", out)

    def test_ignored_mark_survives_feed_replacement_and_stops_digest(self):
        self.collect([item(1), item(2)], DAY1)
        self.edit("feed", lambda f: f["items"][0].update(status="ignored"))
        ignored_id = self.read("feed")["items"][0]["id"]
        self.collect([item(3)], DAY1_EVE)                 # page replaced before the digest
        pending = {p["id"]: p.get("status") for p in self.read("feed")["pending"]}
        self.assertEqual(pending[ignored_id], "ignored")
        out = self.notify("2026-10-18T09:01:00+09:00", "--dry-run")
        self.assertIn("ntfy daily: 2/2 items", out)       # item 2 + item 3, not item 1
        self.assert_valid()

    def test_item_that_ended_while_queued_is_not_sent(self):
        self.collect([item(1, ends="2026-10-17"), item(2)], DAY1)
        out = self.notify("2026-10-18T09:01:00+09:00", "--dry-run")
        self.assertIn("ntfy daily: 1/1 items", out)

    def test_instant_waits_for_quiet_hours(self):
        self.edit("config", lambda c: c["categories"][0].update(priority="instant"))
        self.collect([item(1)], "2026-10-17T23:30:00+09:00")
        self.assertIn("0 items sent", self.notify("2026-10-17T23:31:00+09:00", "--dry-run"))
        self.assertIn("ntfy instant: 1/1", self.notify("2026-10-18T09:00:00+09:00", "--dry-run"))

    def test_weekly_goes_out_on_monday(self):
        self.edit("config", lambda c: c["categories"][0].update(priority="weekly"))
        self.edit("notifiers", lambda n: n["channels"][0].update(priorities=["weekly"]))
        self.collect([item(1)], DAY1)
        self.assertIn("0 items sent", self.notify("2026-10-18T09:01:00+09:00", "--dry-run"))  # Sunday
        self.assertIn("ntfy weekly: 1/1", self.notify("2026-10-19T09:01:00+09:00", "--dry-run"))  # Monday

    def test_source_failing_three_times_alerts_once_a_day(self):
        for hour in ("09", "13", "17"):
            self.run_script("run_deterministic.py", "--no-sources", "--source-error", "rss:x=HTTP 404",
                            now=f"2026-10-17T{hour}:00:00+09:00")
        with self.fake_ntfy() as sent:
            self.notify("2026-10-17T17:01:00+09:00")
            self.run_script("run_deterministic.py", "--no-sources", "--source-error", "rss:x=HTTP 404",
                            now="2026-10-17T19:00:00+09:00")
            self.notify("2026-10-17T19:01:00+09:00")
        alerts = [p for p in sent if "소스 실패" in p["title"]]
        self.assertEqual(len(alerts), 1)
        self.assertIn("rss:x 3회 연속 실패", alerts[0]["message"])

    def test_health_alert(self):
        self.collect([], DAY1)
        out = self.run_script("notify.py", "--health-alert", "--dry-run",
                              now="2026-10-19T10:00:00+09:00", env=NTFY).stdout
        self.assertIn("49시간째 실행되지 않음", out)

    def fake_ntfy(self):
        """Capture ntfy payloads: DEALBOT_HTTP_LOG makes common.http_request log instead of send."""
        test, log = self, self.tmp / "http.jsonl"

        class Capture(list):
            def __enter__(self_):
                test.env["DEALBOT_HTTP_LOG"] = str(log)
                return self_

            def __exit__(self_, *exc):
                del test.env["DEALBOT_HTTP_LOG"]
                if log.exists():
                    self_.extend(json.loads(line)["json"] for line in log.read_text(encoding="utf-8").splitlines())
        return Capture()


class ReviewTest(DataDirTest):
    def test_review_reports_drops_and_feedback(self):
        self.edit("config", lambda c: c.update(min_days_left=1))
        self.collect([item(1), item(2, ends=None)], DAY1)
        self.edit("feed", lambda f: f["items"][0].update(status="ignored"))
        self.collect([item(3, ends="2026-10-01"), item(4)], DAY1_EVE)
        report = json.loads(self.run_script("review_run.py").stdout)
        kinds = {f["type"] for f in report["findings"]}
        self.assertIn("dropped_ended", kinds)
        self.assertIn("user_ignored", kinds)
        self.assertIn("missing_ends", kinds)
        self.assertEqual(report["run"]["new"], 1)

    def test_playbook_is_validated(self):
        self.assert_valid()
        (self.data / "playbook.md").write_text("# 검색 플레이북\n## 검색어\n", encoding="utf-8")
        out = self.run_script("validate.py", check=False)
        self.assertEqual(out.returncode, 1)
        self.assertIn("section '## 우선 출처' is missing", out.stdout)
        (self.data / "playbook.md").write_text("x" * 13000, encoding="utf-8")
        self.assertIn("exceeds", self.run_script("validate.py", check=False).stdout)


class ValidateTest(DataDirTest):
    def test_defaults_are_valid(self):
        self.assert_valid()

    def test_schema_errors(self):
        self.edit("config", lambda c: c["categories"][0].update(keywords=[]))
        out = self.run_script("validate.py", check=False)
        self.assertEqual(out.returncode, 1)
        self.assertIn("keywords", out.stdout)

    def test_secret_detection(self):
        self.edit("notifiers", lambda n: n["channels"][1].update(target="https://hooks.slack.com/services/T0/B0/x"))
        self.assertIn("credential", self.run_script("validate.py", check=False).stdout)

    def test_record_appends_error_to_latest_run(self):
        self.collect([], DAY1)
        self.edit("config", lambda c: c.update(feed_limit=1))
        self.edit("feed", lambda f: f.update(items=[dict(item(1), id="a", key="k1", found_at=DAY1, notified=[], status="new"),
                                                    dict(item(2), id="b", key="k2", found_at=DAY1, notified=[], status="new")]))
        self.run_script("validate.py", "--record", check=False)
        self.assertEqual(self.read("runs")["runs"][0]["errors"][-1]["source"], "validate")


if __name__ == "__main__":
    unittest.main()
