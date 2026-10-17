"""ran_today.py and local_run.py (Codex app scheduled task on the PC).

local_run is exercised against a throwaway git repo (copy of the working tree) whose origin is a
local bare repo, so nothing is ever pushed to GitHub. Its `sh` is wrapped to add --no-sources to
run_deterministic (no network) and to skip pip.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from helpers import ROOT, DataDirTest, item

import ran_today as ran_today_mod

NOW = "2026-10-18T09:05:00+09:00"


def git(cwd, *args, check=True) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True,
                          encoding="utf-8").stdout


# ------------------------------------------------------------------ ran_today

class RanTodayTest(unittest.TestCase):
    def setUp(self):
        from zoneinfo import ZoneInfo
        self.now = datetime(2026, 10, 18, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    def runs(self, at):
        return {"runs": [{"at": at}]}

    def test_run_earlier_today_counts(self):
        self.assertTrue(ran_today_mod.ran_today(self.runs("2026-10-18T08:59:00+09:00"), self.now))

    def test_run_yesterday_does_not_count(self):
        self.assertFalse(ran_today_mod.ran_today(self.runs("2026-10-17T09:00:00+09:00"), self.now))

    def test_empty_history_does_not_count(self):
        self.assertFalse(ran_today_mod.ran_today({"runs": []}, self.now))
        self.assertFalse(ran_today_mod.ran_today({}, self.now))

    def test_just_after_local_midnight_is_today(self):
        self.assertTrue(ran_today_mod.ran_today(self.runs("2026-10-18T00:30:00+09:00"), self.now))

    def test_just_before_local_midnight_is_yesterday(self):
        self.assertFalse(ran_today_mod.ran_today(self.runs("2026-10-17T23:50:00+09:00"), self.now))

    def test_utc_timestamp_is_compared_in_local_timezone(self):
        # 2026-10-17 15:30 UTC == 2026-10-18 00:30 KST
        self.assertTrue(ran_today_mod.ran_today(self.runs("2026-10-17T15:30:00+00:00"), self.now))
        # 2026-10-17 14:50 UTC == 2026-10-17 23:50 KST
        self.assertFalse(ran_today_mod.ran_today(self.runs("2026-10-17T14:50:00+00:00"), self.now))

    def test_only_the_latest_run_matters(self):
        runs = {"runs": [{"at": "2026-10-17T09:00:00+09:00"}, {"at": "2026-10-18T08:00:00+09:00"}]}
        self.assertFalse(ran_today_mod.ran_today(runs, self.now))


class RanTodayCliTest(DataDirTest):
    def test_cli_prints_yes_after_a_run_today_and_no_otherwise(self):
        self.assertEqual(self.run_script("ran_today.py", now=NOW).stdout.strip(), "no")
        self.write("runs", {"runs": [{"at": "2026-10-18T00:30:00+09:00", "found": 0, "new": 0,
                                       "notified": 0, "by_source": {}, "errors": []}]})
        self.assertEqual(self.run_script("ran_today.py", now=NOW).stdout.strip(), "yes")
        self.assertEqual(self.run_script("ran_today.py", now="2026-10-19T00:10:00+09:00").stdout.strip(), "no")


# ------------------------------------------------------------------ local_run

def tracked_files() -> list[str]:
    out = git(ROOT, "ls-files", "-z")
    return [p for p in out.split("\0") if p and (ROOT / p).is_file()]


class LocalRunTest(unittest.TestCase):
    """Each test gets a fresh clone of a fresh bare remote seeded from the working tree."""

    @classmethod
    def setUpClass(cls):
        if not shutil.which("git"):
            raise unittest.SkipTest("git not available")
        cls.base = Path(tempfile.mkdtemp(prefix="dealbot-localrun-"))
        src = cls.base / "src"
        for rel in tracked_files():
            dst = src / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dst)
        data = src / "data"
        for name, obj in (("feed", {"run_at": None, "items": [], "pending": [], "bought": []}),
                          ("seen", {"keys": {}}), ("runs", {"runs": []})):
            (data / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        git(src, "init", "-q", "-b", "main")
        git(src, "config", "user.name", "test")
        git(src, "config", "user.email", "test@example.invalid")
        git(src, "config", "core.autocrlf", "false")
        git(src, "add", "-A")
        git(src, "commit", "-q", "-m", "seed")
        cls.template = cls.base / "template.git"
        git(cls.base, "clone", "-q", "--bare", str(src), str(cls.template))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="t-", dir=self.base))
        self.remote = self.tmp / "remote.git"
        shutil.copytree(self.template, self.remote)
        self.work = self.tmp / "work"
        git(self.tmp, "clone", "-q", str(self.remote), str(self.work))
        git(self.work, "config", "user.name", "test")
        git(self.work, "config", "user.email", "test@example.invalid")
        git(self.work, "config", "core.autocrlf", "false")
        # load the product module and point it at the clone
        spec = importlib.util.spec_from_file_location(f"local_run_{id(self)}", ROOT / "scripts/local_run.py")
        self.lr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.lr)
        self.lr.ROOT = self.work
        self.lr.TMP = self.work / ".tmp"
        self.lr.VENV_PY = Path(sys.executable)
        self.log: list[str] = []
        real_sh = self.lr.sh

        def fake_sh(*cmd, check=True, capture=False):
            cmd = list(cmd)
            if "-m" in cmd and "pip" in cmd:
                self.log.append("skip pip")
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if any(str(c).endswith("run_deterministic.py") for c in cmd):
                cmd.insert(2, "--no-sources")
            proc = real_sh(*cmd, check=False, capture=True)
            self.log.append(f"$ {' '.join(map(str, cmd))} -> {proc.returncode}\n{proc.stdout}{proc.stderr}")
            if check and proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, cmd, proc.stdout, proc.stderr)
            return proc

        self.lr.sh = fake_sh
        env = {k: v for k, v in os.environ.items() if not k.startswith("DEALBOT_")}
        env["DEALBOT_NOW"] = NOW
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.lr.TMP.mkdir(exist_ok=True)
        self.remote_head = self.head(self.remote)

    def tearDown(self):
        self.env.stop()

    # --- helpers
    def call(self, fn, *args) -> int:
        with mock.patch("sys.stdout", new=_Sink()) as out:
            rc = fn(*args)
        self.log.append(out.text)
        return rc

    def head(self, repo) -> str:
        return git(repo, "rev-parse", "main").strip()

    def remote_msg(self) -> str:
        return git(self.remote, "log", "-1", "--format=%s", "main").strip()

    def remote_json(self, name):
        return json.loads(git(self.remote, "show", f"main:data/{name}.json"))

    def remote_text(self, path):
        return git(self.remote, "show", f"main:{path}")

    def search(self, obj):
        (self.lr.TMP / "search.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def break_playbook(self):
        pb = self.work / "data/playbook.md"
        pb.write_text(pb.read_text(encoding="utf-8").replace("## 검색어", "## 검색 (renamed)"), encoding="utf-8")

    def dump(self):
        return "\n".join(self.log)

    # --- tests
    def test_collect_then_publish_pushes_a_codex_run_commit(self):
        self.search([item(1), item(2)])
        self.assertEqual(self.call(self.lr.collect, None), 0, self.dump())
        review = json.loads((self.lr.TMP / "review.json").read_text(encoding="utf-8"))
        self.assertIn("findings", review)
        self.assertEqual(self.call(self.lr.publish), 0, self.dump())
        self.assertNotEqual(self.head(self.remote), self.remote_head)
        self.assertEqual(self.remote_msg(), "codex: run 2026-10-18 09:05 (+2 new)")
        self.assertEqual(self.remote_json("runs")["runs"][0]["new"], 2)
        self.assertEqual(len(self.remote_json("feed")["items"]), 2)
        changed = git(self.remote, "diff", "--name-only", f"{self.remote_head}..main").split()
        self.assertTrue(changed and all(p.startswith("data/") for p in changed), changed)
        self.assertEqual(git(self.work, "status", "--porcelain").strip(), "")

    def test_publish_refuses_when_files_outside_data_changed(self):
        self.search([item(1)])
        self.assertEqual(self.call(self.lr.collect, None), 0, self.dump())
        (self.work / "docs/x.txt").write_text("stray", encoding="utf-8")
        local_head = self.head(self.work)
        self.assertEqual(self.call(self.lr.publish), 1, self.dump())
        self.assertIn("refusing to publish", self.dump())
        self.assertEqual(self.head(self.work), local_head)
        self.assertEqual(self.head(self.remote), self.remote_head)

    def test_publish_refuses_when_a_tracked_script_was_edited(self):
        self.assertEqual(self.call(self.lr.collect, None), 0, self.dump())
        p = self.work / "scripts/common.py"
        p.write_text(p.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
        self.assertEqual(self.call(self.lr.publish), 1, self.dump())
        self.assertEqual(self.head(self.remote), self.remote_head)

    def test_broken_playbook_is_restored_and_the_rest_is_published(self):
        original = (self.work / "data/playbook.md").read_text(encoding="utf-8")
        self.search([item(1)])
        self.assertEqual(self.call(self.lr.collect, None), 0, self.dump())
        self.break_playbook()
        self.assertEqual(self.call(self.lr.publish), 0, self.dump())
        self.assertIn("restoring it", self.dump())
        self.assertEqual(self.remote_text("data/playbook.md"), original)
        self.assertEqual(len(self.remote_json("feed")["items"]), 1)
        self.assertEqual(self.remote_msg(), "codex: run 2026-10-18 09:05 (+1 new)")

    def test_valid_playbook_edit_is_published(self):
        self.assertEqual(self.call(self.lr.collect, None), 0, self.dump())
        pb = self.work / "data/playbook.md"
        pb.write_text(pb.read_text(encoding="utf-8") + "\n- 새 메모\n", encoding="utf-8")
        self.assertEqual(self.call(self.lr.publish), 0, self.dump())
        self.assertIn("- 새 메모", self.remote_text("data/playbook.md"))

    def test_non_array_search_file_is_recorded_as_source_error(self):
        self.search({"items": [item(1)]})
        self.assertEqual(self.call(self.lr.collect, None), 0, self.dump())
        run = json.loads((self.work / "data/runs.json").read_text(encoding="utf-8"))["runs"][0]
        self.assertEqual(run["new"], 0)
        self.assertTrue(any(e["source"] == "search" and "not a JSON array" in e["error"] for e in run["errors"]),
                        run["errors"])

    def test_invalid_json_search_file_is_recorded_as_source_error(self):
        (self.lr.TMP / "search.json").write_text("[{broken", encoding="utf-8")
        self.assertEqual(self.call(self.lr.collect, None), 0, self.dump())
        run = json.loads((self.work / "data/runs.json").read_text(encoding="utf-8"))["runs"][0]
        self.assertTrue(any(e["source"] == "search" for e in run["errors"]), run["errors"])

    def test_search_error_option_is_recorded(self):
        self.assertEqual(self.call(self.lr.collect, "웹 검색 차단"), 0, self.dump())
        run = json.loads((self.work / "data/runs.json").read_text(encoding="utf-8"))["runs"][0]
        self.assertIn({"source": "search", "error": "웹 검색 차단"}, run["errors"])

    def test_validate_failure_restores_feed_seen_playbook_and_publishes_the_run(self):
        original = (self.work / "data/playbook.md").read_text(encoding="utf-8")
        self.break_playbook()  # makes validate --record fail right after collection
        self.search([item(1)])
        self.assertEqual(self.call(self.lr.collect, None), 1, self.dump())
        self.assertTrue((self.lr.TMP / "validate_failed").exists())
        self.assertFalse((self.lr.TMP / "review.json").exists())
        self.assertEqual(self.call(self.lr.publish), 0, self.dump())
        self.assertEqual(self.remote_msg(), "codex: run 2026-10-18 09:05 (+1 new) (validate failed)")
        self.assertEqual(self.remote_json("feed")["items"], [])
        self.assertEqual(self.remote_json("seen")["keys"], {})
        self.assertEqual(self.remote_text("data/playbook.md"), original)
        run = self.remote_json("runs")["runs"][0]
        self.assertTrue(any(e["source"] == "validate" for e in run["errors"]), run["errors"])
        self.assertFalse((self.lr.TMP / "validate_failed").exists())

    def test_publish_with_nothing_changed_makes_no_commit(self):
        self.assertEqual(self.call(self.lr.publish), 0, self.dump())
        self.assertIn("nothing to commit", self.dump())
        self.assertEqual(self.head(self.remote), self.remote_head)

    def test_publish_rebases_onto_a_newer_remote_commit(self):
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(self.remote), str(other))
        git(other, "config", "user.name", "ui")
        git(other, "config", "user.email", "ui@example.invalid")
        cfg = json.loads((other / "data/config.json").read_text(encoding="utf-8"))
        (other / "data/config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8")
        git(other, "commit", "-q", "-am", "ui: config")
        git(other, "push", "-q", "origin", "main")
        self.search([item(1)])
        self.assertEqual(self.call(self.lr.collect, None), 0, self.dump())
        self.assertEqual(self.call(self.lr.publish), 0, self.dump())
        log = git(self.remote, "log", "--format=%s", "-3", "main").splitlines()
        self.assertEqual(log[:2], ["codex: run 2026-10-18 09:05 (+1 new)", "ui: config"])

    def test_prepare_pulls_and_clears_stale_search_and_review(self):
        self.search([item(9)])
        (self.lr.TMP / "review.json").write_text("{}", encoding="utf-8")
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(self.remote), str(other))
        git(other, "config", "user.name", "ui")
        git(other, "config", "user.email", "ui@example.invalid")
        (other / "data/links.json").write_text(
            (other / "data/links.json").read_text(encoding="utf-8") + "\n", encoding="utf-8")
        git(other, "commit", "-q", "-am", "ui: links")
        git(other, "push", "-q", "origin", "main")
        self.assertEqual(self.call(self.lr.prepare), 0, self.dump())
        self.assertFalse((self.lr.TMP / "search.json").exists())
        self.assertFalse((self.lr.TMP / "review.json").exists())
        self.assertEqual(self.head(self.work), self.head(self.remote))


class _Sink:
    def __init__(self):
        self.parts = []

    def write(self, s):
        self.parts.append(s)
        return len(s)

    def flush(self):
        pass

    @property
    def text(self):
        return "".join(self.parts)


# ------------------------------------------------------------------ workflows

class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import yaml
        except ImportError:
            raise unittest.SkipTest("pyyaml not installed")
        cls.wf = {}
        for name in ("notify", "dealbot"):
            doc = yaml.safe_load((ROOT / f".github/workflows/{name}.yml").read_text(encoding="utf-8"))
            doc["on"] = doc.pop(True, doc.get("on"))  # YAML 1.1 reads `on` as true
            cls.wf[name] = doc

    def test_notify_runs_on_codex_run_pushes_to_runs_json(self):
        wf = self.wf["notify"]
        self.assertEqual(wf["on"]["push"]["branches"], ["main"])
        self.assertEqual(wf["on"]["push"]["paths"], ["data/runs.json"])
        self.assertIn("workflow_dispatch", wf["on"])
        cond = " ".join(wf["jobs"]["notify"]["if"].split())
        self.assertIn("github.event_name == 'workflow_dispatch'", cond)
        self.assertIn("startsWith(github.event.head_commit.message, 'codex: run')", cond)
        runs = [s.get("run", "") for s in wf["jobs"]["notify"]["steps"]]
        self.assertTrue(any("notify.py --since-run" in r for r in runs))

    def test_notify_shares_the_data_concurrency_group(self):
        self.assertEqual(self.wf["notify"]["concurrency"]["group"], self.wf["dealbot"]["concurrency"]["group"])

    def test_dealbot_runs_at_10_kst_behind_a_gate(self):
        wf = self.wf["dealbot"]
        self.assertEqual(wf["on"]["schedule"], [{"cron": "0 1 * * *"}])
        jobs = wf["jobs"]
        self.assertEqual(jobs["gate"]["outputs"]["go"], "${{ steps.check.outputs.go }}")
        gate_run = jobs["gate"]["steps"][-1]["run"]
        self.assertIn("scripts/ran_today.py", gate_run)
        self.assertIn('"schedule"', gate_run)
        self.assertEqual(jobs["search"]["needs"], "gate")
        self.assertEqual(jobs["search"]["if"], "needs.gate.outputs.go == 'true'")
        self.assertEqual(jobs["collect"]["needs"], ["gate", "search"])
        self.assertEqual(jobs["collect"]["if"], "always() && needs.gate.outputs.go == 'true'")

    def test_run_blocks_are_valid_bash(self):
        import re
        bash = shutil.which("bash")
        if not bash or "system32" in bash.lower():
            self.skipTest("bash not available")
        for name, wf in self.wf.items():
            for job_id, job in wf["jobs"].items():
                for i, step in enumerate(job.get("steps", [])):
                    if "run" not in step:
                        continue
                    script = re.sub(r"\$\{\{.*?\}\}", "X", step["run"])
                    proc = subprocess.run([bash, "-n"], input=script, capture_output=True, text=True,
                                          encoding="utf-8")
                    self.assertEqual(proc.returncode, 0, f"{name}.{job_id}[{i}]: {proc.stderr}")


if __name__ == "__main__":
    unittest.main()
