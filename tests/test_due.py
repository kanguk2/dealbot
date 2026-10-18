"""due.py (24h interval / page requests) and how run_deterministic closes requests."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from helpers import DataDirTest, item

import due
import validate as validate_mod

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 18, 9, 0, tzinfo=KST)


def runs_at(*ats):
    return {"runs": [{"at": a.isoformat() if isinstance(a, datetime) else a} for a in ats]}


def req(at, status="open", rid="r1", done_at=None):
    return {"id": rid, "requested_at": at.isoformat() if isinstance(at, datetime) else at,
            "status": status, "done_at": done_at}


NO_REQ = {"requests": []}


class IsDueTest(unittest.TestCase):
    def test_last_run_22h59m_ago_is_not_due_with_24h_interval(self):
        ok, why = due.is_due(runs_at(NOW - timedelta(hours=22, minutes=59)), NO_REQ, NOW, 24)
        self.assertFalse(ok, why)
        self.assertIn("열린 요청 없음", why)

    def test_last_run_23h_ago_is_due_because_of_polling_drift_tolerance(self):
        ok, why = due.is_due(runs_at(NOW - timedelta(hours=23)), NO_REQ, NOW, 24)
        self.assertTrue(ok, why)
        self.assertIn("23시간", why)

    def test_interval_hours_is_honoured(self):
        last = runs_at(NOW - timedelta(hours=5))
        self.assertTrue(due.is_due(last, NO_REQ, NOW, 6)[0])    # wait 5h
        self.assertFalse(due.is_due(last, NO_REQ, NOW, 7)[0])   # wait 6h

    def test_slack_delays_the_interval_run(self):
        last = runs_at(NOW - timedelta(hours=25, minutes=59))
        self.assertFalse(due.is_due(last, NO_REQ, NOW, 24, slack_hours=3)[0])
        self.assertTrue(due.is_due(runs_at(NOW - timedelta(hours=26)), NO_REQ, NOW, 24, slack_hours=3)[0])

    def test_no_run_record_is_due(self):
        for runs in ({"runs": []}, {}, None):
            ok, why = due.is_due(runs, NO_REQ, NOW, 24)
            self.assertTrue(ok)
            self.assertEqual(why, "실행 기록 없음")

    def test_open_request_makes_it_due_even_right_after_a_run(self):
        ok, why = due.is_due(runs_at(NOW - timedelta(minutes=10)),
                             {"requests": [req(NOW - timedelta(minutes=1))]}, NOW, 24)
        self.assertTrue(ok)
        self.assertIn("페이지 요청", why)

    def test_request_wait_holds_back_a_fresh_request(self):
        recent = runs_at(NOW - timedelta(hours=1))
        young = {"requests": [req(NOW - timedelta(hours=1, minutes=59))]}
        old = {"requests": [req(NOW - timedelta(hours=2))]}
        self.assertFalse(due.is_due(recent, young, NOW, 24, request_wait_hours=2)[0])
        self.assertTrue(due.is_due(recent, old, NOW, 24, request_wait_hours=2)[0])

    def test_done_requests_are_ignored(self):
        done = {"requests": [req(NOW - timedelta(hours=5), status="done", done_at=NOW.isoformat())]}
        self.assertFalse(due.is_due(runs_at(NOW - timedelta(hours=1)), done, NOW, 24)[0])

    def test_missing_requests_file_is_like_no_requests(self):
        self.assertFalse(due.is_due(runs_at(NOW - timedelta(hours=1)), None, NOW, 24)[0])

    def test_only_the_latest_run_matters(self):
        runs = runs_at(NOW - timedelta(hours=1), NOW - timedelta(hours=48))
        self.assertFalse(due.is_due(runs, NO_REQ, NOW, 24)[0])

    def test_utc_timestamps_compare_correctly(self):
        # 2026-10-17 01:00 UTC == 10:00 KST, 23h before NOW
        self.assertTrue(due.is_due(runs_at("2026-10-17T01:00:00+00:00"), NO_REQ, NOW, 24)[0])
        self.assertFalse(due.is_due(runs_at("2026-10-17T01:01:00+00:00"), NO_REQ, NOW, 24)[0])


class CloseRequestsTest(unittest.TestCase):
    def test_requests_made_before_the_run_are_closed_with_done_at(self):
        data = {"requests": [req(NOW - timedelta(minutes=30))]}
        self.assertEqual(due.close_requests(data, NOW), 1)
        self.assertEqual(data["requests"][0]["status"], "done")
        self.assertEqual(data["requests"][0]["done_at"], NOW.isoformat())

    def test_requests_made_after_the_run_started_stay_open(self):
        data = {"requests": [req(NOW - timedelta(minutes=5), rid="a"), req(NOW + timedelta(minutes=1), rid="b")]}
        self.assertEqual(due.close_requests(data, NOW), 1)
        self.assertEqual([r["status"] for r in data["requests"]], ["done", "open"])
        self.assertIsNone(data["requests"][1]["done_at"])

    def test_already_done_requests_are_not_touched(self):
        old = req(NOW - timedelta(days=1), status="done", done_at="2026-10-17T10:00:00+09:00")
        data = {"requests": [dict(old)]}
        self.assertEqual(due.close_requests(data, NOW), 0)
        self.assertEqual(data["requests"], [old])

    def test_only_the_latest_50_are_kept(self):
        data = {"requests": [req(NOW - timedelta(minutes=60 - i), status="done", rid=f"r{i}",
                                 done_at=NOW.isoformat()) for i in range(55)]}
        data["requests"].append(req(NOW - timedelta(seconds=1), rid="last"))
        self.assertEqual(due.close_requests(data, NOW), 1)
        self.assertEqual(len(data["requests"]), 50)
        self.assertEqual(data["requests"][-1]["id"], "last")
        self.assertEqual(data["requests"][0]["id"], "r6")


class DueCliTest(DataDirTest):
    def test_cli_prints_yes_or_no_with_a_reason(self):
        out = self.run_script("due.py", now="2026-10-18T09:00:00+09:00").stdout.strip()
        self.assertEqual(out, "yes 실행 기록 없음")
        self.write("runs", {"runs": [{"at": "2026-10-18T08:00:00+09:00", "found": 0, "new": 0,
                                       "notified": 0, "by_source": {}, "errors": []}]})
        self.assertTrue(self.run_script("due.py", now="2026-10-18T09:00:00+09:00").stdout.startswith("no "))
        self.assertTrue(self.run_script("due.py", now="2026-10-19T07:00:00+09:00").stdout.startswith("yes "))
        # Actions gate: 3h slack
        self.assertTrue(self.run_script("due.py", "--slack", "3", now="2026-10-19T09:59:00+09:00")
                        .stdout.startswith("no "))
        self.assertTrue(self.run_script("due.py", "--slack", "3", now="2026-10-19T10:00:00+09:00")
                        .stdout.startswith("yes "))

    def test_cli_reads_interval_from_config_and_requests_from_data(self):
        self.write("runs", {"runs": [{"at": "2026-10-18T08:00:00+09:00", "found": 0, "new": 0,
                                       "notified": 0, "by_source": {}, "errors": []}]})
        self.edit("config", lambda c: c["schedule"].update(interval_hours=3))
        self.assertTrue(self.run_script("due.py", now="2026-10-18T10:00:00+09:00").stdout.startswith("yes "))
        self.edit("config", lambda c: c["schedule"].update(interval_hours=24))
        self.write("requests", {"requests": [req("2026-10-18T09:30:00+09:00")]})
        self.assertTrue(self.run_script("due.py", now="2026-10-18T10:00:00+09:00").stdout.startswith("yes 페이지 요청"))
        self.assertTrue(self.run_script("due.py", "--request-wait", "2", now="2026-10-18T10:00:00+09:00")
                        .stdout.startswith("no "))

    def test_cli_works_without_a_requests_file(self):
        (self.data / "requests.json").unlink()
        self.assertTrue(self.run_script("due.py", now="2026-10-18T09:00:00+09:00").stdout.startswith("yes "))


class RunClosesRequestsTest(DataDirTest):
    RUN = "2026-10-18T10:00:00+09:00"

    def test_a_run_closes_open_requests_made_before_it(self):
        self.write("requests", {"requests": [req("2026-10-18T09:30:00+09:00", rid="a"),
                                             req("2026-10-18T10:05:00+09:00", rid="b")]})
        self.collect([item(1)], self.RUN)
        reqs = self.read("requests")["requests"]
        self.assertEqual([(r["id"], r["status"]) for r in reqs], [("a", "done"), ("b", "open")])
        self.assertEqual(datetime.fromisoformat(reqs[0]["done_at"]), datetime.fromisoformat(self.RUN))
        self.assert_valid()
        # due.py no longer sees request a; b is still waiting
        out = self.run_script("due.py", now="2026-10-18T10:06:00+09:00").stdout
        self.assertIn("10/18 10:05", out)

    def test_run_without_open_requests_leaves_the_file_untouched(self):
        raw = '{"requests": []}'
        (self.data / "requests.json").write_text(raw, encoding="utf-8")
        self.collect([item(1)], self.RUN)
        self.assertEqual((self.data / "requests.json").read_text(encoding="utf-8"), raw)

    def test_run_without_a_requests_file_does_not_create_one(self):
        (self.data / "requests.json").unlink()
        self.collect([item(1)], self.RUN)
        self.assertFalse((self.data / "requests.json").exists())

    def test_due_is_no_after_the_run_that_answered_a_request(self):
        self.write("requests", {"requests": [req("2026-10-18T09:30:00+09:00")]})
        self.assertTrue(self.run_script("due.py", now=self.RUN).stdout.startswith("yes 페이지 요청"))
        self.collect([], self.RUN)
        self.assertTrue(self.run_script("due.py", now="2026-10-18T10:30:00+09:00").stdout.startswith("no "))


class ScheduleSchemaTest(unittest.TestCase):
    def config(self, **schedule):
        import json
        from helpers import ROOT
        cfg = json.loads((ROOT / "data/config.json").read_text(encoding="utf-8"))
        cfg["schedule"] = {"timezone": "Asia/Seoul", **schedule}
        return cfg

    def test_interval_hours_between_1_and_168_is_valid(self):
        for n in (1, 24, 168):
            self.assertEqual(validate_mod.schema_problems("config", self.config(interval_hours=n)), [], n)

    def test_interval_hours_out_of_range_or_not_integer_fails(self):
        for n in (0, 169, 1.5, "24"):
            self.assertTrue(validate_mod.schema_problems("config", self.config(interval_hours=n)), n)

    def test_old_times_field_is_rejected(self):
        probs = validate_mod.schema_problems("config", self.config(interval_hours=24, times=["09:00"]))
        self.assertTrue(any("times" in p for p in probs), probs)
        probs = validate_mod.schema_problems("config", self.config(times=["09:00"]))
        self.assertTrue(any("interval_hours" in p for p in probs), probs)

    def test_requests_schema_accepts_open_and_done_and_rejects_others(self):
        ok = {"requests": [req(NOW), req(NOW, status="done", rid="r2", done_at=NOW.isoformat())]}
        self.assertEqual(validate_mod.schema_problems("requests", ok), [])
        self.assertTrue(validate_mod.schema_problems("requests", {"requests": [req(NOW, status="running")]}))
        self.assertTrue(validate_mod.schema_problems("requests", {"requests": [req(NOW)] * 51}))
        self.assertTrue(validate_mod.schema_problems("requests", {"requests": [{"id": "x", "status": "open"}]}))


if __name__ == "__main__":
    unittest.main()
