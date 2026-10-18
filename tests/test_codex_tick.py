"""codex_tick.py (Windows Task Scheduler entry point) end to end, with a fake Codex.

Each test runs the real scripts/codex_tick.py inside a throwaway clone (copy of the working tree)
whose origin is a local bare repo. Nothing reaches GitHub, OpenAI or any deal site:
  - DEALBOT_CODEX = this Python; codex_tick calls `<python> exec ...`, so Python runs the file
    named `exec` in the clone root (our fake Codex, hidden from git via .git/info/exclude)
  - DEALBOT_HTTP_LOG turns every RSS fetch into a logged no-op
  - the clone's .venv is a link to this repo's .venv, so local_run.py never builds a venv
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from helpers import ROOT, item
from test_local_run import git, tracked_files

NOW = "2026-10-18T09:05:00+09:00"
TICK_TIMEOUT = 180

FAKE_CODEX = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
step = "search" if 'web_search="live"' in args else "review"
root = Path(args[args.index("-C") + 1])
with open(os.environ["FAKE_CODEX_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"step": step, "args": args}, ensure_ascii=False) + "\n")
mode = os.environ.get("FAKE_CODEX_MODE", "ok")
if mode == "read_stdin":
    sys.stdin.read()          # blocks forever unless stdin is closed (DEVNULL)
if mode == "fail":
    print("fake codex: boom")
    sys.exit(1)
if step == "search":
    items = json.loads(os.environ.get("FAKE_SEARCH_ITEMS", "[]"))
    if items:
        (root / ".tmp/search.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    if mode == "stray":
        p = root / "docs/index.html"
        p.write_text(p.read_text(encoding="utf-8") + "<!-- codex -->", encoding="utf-8")
        (root / "docs/stray.txt").write_text("x", encoding="utf-8")
        (root / "data/note.md").write_text("x", encoding="utf-8")
    if mode == "stray_dir":
        (root / "newdir").mkdir()
        (root / "newdir/x.txt").write_text("x", encoding="utf-8")
else:
    if mode == "stray":
        (root / "data/feed.json").write_text('{"broken": true}', encoding="utf-8")
        pb = root / "data/playbook.md"
        pb.write_text(pb.read_text(encoding="utf-8") + "\n- 회고 메모\n", encoding="utf-8")
        p = root / "scripts/common.py"
        p.write_text(p.read_text(encoding="utf-8") + "\n# codex edit\n", encoding="utf-8")
    if mode == "new_data_file":
        (root / "data/extra.json").write_text("{}", encoding="utf-8")
print("fake codex done")
'''


def link_dir(link: Path, target: Path) -> None:
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True,
                       capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


class CodexTickTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("git"):
            raise unittest.SkipTest("git not available")
        if not (ROOT / ".venv").exists():
            raise unittest.SkipTest("needs the repo .venv (local_run.py re-execs inside it)")
        cls.base = Path(tempfile.mkdtemp(prefix="dealbot-tick-"))
        src = cls.base / "src"
        for rel in tracked_files():
            dst = src / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dst)
        data = src / "data"
        for name, obj in (("feed", {"run_at": None, "items": [], "pending": [], "bought": []}),
                          ("seen", {"keys": {}}), ("runs", {"runs": []}), ("requests", {"requests": []})):
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
        # remove the .venv links first so rmtree never walks into the real .venv
        for p in cls.base.glob("t-*/work/.venv"):
            if os.name == "nt":
                os.rmdir(p)
            else:
                p.unlink()
        shutil.rmtree(cls.base, ignore_errors=True)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="t-", dir=self.base))
        self.remote = self.tmp / "remote.git"
        shutil.copytree(self.template, self.remote)
        self.work = self.tmp / "work"
        git(self.tmp, "clone", "-q", str(self.remote), str(self.work))
        for k, v in (("user.name", "test"), ("user.email", "test@example.invalid"), ("core.autocrlf", "false")):
            git(self.work, "config", k, v)
        link_dir(self.work / ".venv", ROOT / ".venv")
        (self.work / "exec").write_text(FAKE_CODEX, encoding="utf-8")
        with (self.work / ".git/info/exclude").open("a", encoding="utf-8") as f:
            f.write("\n/exec\n")
        self.codex_log = self.tmp / "codex.log"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("DEALBOT_", "FAKE_"))}
        self.env.update({"DEALBOT_NOW": NOW, "DEALBOT_CODEX": sys.executable,
                         "DEALBOT_HTTP_LOG": str(self.tmp / "http.log"),
                         "FAKE_CODEX_LOG": str(self.codex_log), "PYTHONIOENCODING": "utf-8",
                         "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
        self.remote_head = self.head(self.remote)
        self.out = ""

    # --- helpers
    def tick(self, *args, mode="ok", search=None, timeout=TICK_TIMEOUT, keep_stdin_open=False) -> int:
        env = dict(self.env, FAKE_CODEX_MODE=mode, FAKE_SEARCH_ITEMS=json.dumps(search or [], ensure_ascii=False))
        out_path = self.tmp / "tick.out"
        with out_path.open("w", encoding="utf-8") as out:
            # keep_stdin_open: our end of the pipe stays open, so a child that reads stdin blocks
            proc = subprocess.Popen([sys.executable, str(self.work / "scripts/codex_tick.py"), *args],
                                    cwd=self.work, env=env, stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.PIPE if keep_stdin_open else subprocess.DEVNULL)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.kill_tree(proc)
                self.fail(f"codex_tick did not finish within {timeout}s (a child waited on stdin?)\n"
                          + self.tick_log())
            finally:
                if proc.stdin:
                    proc.stdin.close()
        self.out = out_path.read_text(encoding="utf-8", errors="replace")
        return proc.returncode

    @staticmethod
    def kill_tree(proc):
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass

    def head(self, repo) -> str:
        return git(repo, "rev-parse", "main").strip()

    def remote_msg(self) -> str:
        return git(self.remote, "log", "-1", "--format=%s", "main").strip()

    def remote_json(self, name):
        return json.loads(git(self.remote, "show", f"main:data/{name}.json"))

    def remote_text(self, path):
        return git(self.remote, "show", f"main:{path}")

    def changed_on_remote(self) -> list[str]:
        return git(self.remote, "diff", "--name-only", f"{self.remote_head}..main").split()

    def calls(self) -> list[dict]:
        if not self.codex_log.exists():
            return []
        return [json.loads(l) for l in self.codex_log.read_text(encoding="utf-8").splitlines() if l]

    def tick_log(self) -> str:
        p = self.work / ".tmp/tick.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def dump(self) -> str:
        return f"stdout:\n{self.out}\ntick.log:\n{self.tick_log()}"

    def recent_run(self, at="2026-10-18T08:00:00+09:00"):
        (self.work / "data/runs.json").write_text(json.dumps({"runs": [
            {"at": at, "found": 0, "new": 0, "notified": 0, "by_source": {}, "errors": []}]}), encoding="utf-8")
        git(self.work, "commit", "-q", "-am", "codex: run earlier")
        git(self.work, "push", "-q", "origin", "main")
        self.remote_head = self.head(self.remote)

    # --- tests
    def test_full_tick_calls_search_then_review_and_publishes(self):
        rc = self.tick("--force", search=[item(1), item(2)])
        self.assertEqual(rc, 0, self.dump())
        calls = self.calls()
        self.assertEqual([c["step"] for c in calls], ["search", "review"], self.dump())
        search, review = calls[0]["args"], calls[1]["args"]
        for args in (search, review):
            self.assertEqual(args[0], "--ephemeral")
            self.assertIn('approval_policy="never"', args)
            self.assertEqual(args[args.index("-s") + 1], "workspace-write")
            self.assertEqual(Path(args[args.index("-C") + 1]).resolve(), self.work.resolve())
        self.assertEqual(search[-1], (self.work / ".github/codex/search.md").read_text(encoding="utf-8"))
        self.assertEqual(review[-1], (self.work / ".github/codex/review.md").read_text(encoding="utf-8"))
        self.assertNotIn('web_search="live"', review)
        self.assertTrue(search[search.index("-o") + 1].endswith("search-report.txt"))
        self.assertTrue(review[review.index("-o") + 1].endswith("review-report.txt"))

        self.assertEqual(self.remote_msg(), "codex: run 2026-10-18 09:05 (+2 new)")
        self.assertEqual(len(self.remote_json("feed")["items"]), 2)
        run = self.remote_json("runs")["runs"][0]
        self.assertFalse(any(e["source"] == "search" for e in run["errors"]), run["errors"])
        self.assertEqual(git(self.work, "status", "--porcelain").strip(), "")
        self.assertFalse((self.work / ".tmp/tick.lock").exists())

    def test_codex_edits_outside_allowed_paths_are_discarded_and_playbook_kept(self):
        original_index = (self.work / "docs/index.html").read_text(encoding="utf-8")
        original_common = (self.work / "scripts/common.py").read_text(encoding="utf-8")
        rc = self.tick("--force", mode="stray", search=[item(1)])
        self.assertEqual(rc, 0, self.dump())
        self.assertIn("discarding Codex edits outside .tmp/", self.tick_log())
        self.assertIn("discarding Codex edits besides data/playbook.md", self.tick_log())
        # search step: tracked docs/ edit restored, new files removed (data/ is off limits too)
        self.assertEqual((self.work / "docs/index.html").read_text(encoding="utf-8"), original_index)
        self.assertFalse((self.work / "docs/stray.txt").exists())
        self.assertFalse((self.work / "data/note.md").exists())
        # review step: script edit restored, data/*.json back to the collect output, playbook kept
        self.assertEqual((self.work / "scripts/common.py").read_text(encoding="utf-8"), original_common)
        feed = self.remote_json("feed")
        self.assertEqual([i["title"] for i in feed["items"]], ["테스트 적립 이벤트 1"])
        self.assertIn("- 회고 메모", self.remote_text("data/playbook.md"))
        changed = self.changed_on_remote()
        self.assertTrue(changed and all(p.startswith("data/") for p in changed), changed)
        self.assertNotIn("data/note.md", changed)
        self.assertEqual(self.remote_msg(), "codex: run 2026-10-18 09:05 (+1 new)")

    # BUG (reported, not fixed here): restore() calls Path.unlink on "?? newdir/" -> PermissionError,
    # the whole tick crashes and nothing is published. Fixed in codex_tick.restore().
    def test_new_untracked_directory_from_codex_does_not_crash_the_tick(self):
        rc = self.tick("--force", mode="stray_dir", search=[item(1)])
        self.assertEqual(rc, 0, self.dump())
        self.assertNotIn("tick crashed", self.tick_log())
        self.assertFalse((self.work / "newdir").exists())
        self.assertEqual(self.remote_msg(), "codex: run 2026-10-18 09:05 (+1 new)")

    # BUG (reported, not fixed here): the review step only restores data/*.json files that existed
    # before it, so a new data/ file written by Codex is committed by publish. Remove once fixed.
    def test_new_data_file_from_review_is_not_published(self):
        rc = self.tick("--force", mode="new_data_file", search=[item(1)])
        self.assertEqual(rc, 0, self.dump())
        self.assertNotIn("data/extra.json", self.changed_on_remote())

    def test_failed_search_without_results_is_recorded_and_the_run_still_publishes(self):
        rc = self.tick("--force", mode="fail")
        self.assertEqual(rc, 0, self.dump())
        self.assertEqual([c["step"] for c in self.calls()], ["search", "review"])
        self.assertIn("codex search: exit 1", self.tick_log())
        run = self.remote_json("runs")["runs"][0]
        self.assertIn({"source": "search", "error": "Codex 검색 실행 실패 (.tmp/tick.log)"}, run["errors"])
        self.assertTrue(self.remote_msg().startswith("codex: run 2026-10-18 09:05"), self.remote_msg())

    def test_codex_never_waits_on_stdin(self):
        # the fake reads stdin to EOF; with an inherited open pipe it would block until killed
        rc = self.tick("--force", mode="read_stdin", search=[item(1)], timeout=90, keep_stdin_open=True)
        self.assertEqual(rc, 0, self.dump())
        self.assertEqual([c["step"] for c in self.calls()], ["search", "review"])
        self.assertNotIn("timed out", self.tick_log())

    def test_skip_when_not_due_calls_no_codex_and_pushes_nothing(self):
        self.recent_run()
        rc = self.tick(search=[item(1)])
        self.assertEqual(rc, 0, self.dump())
        self.assertEqual(self.calls(), [])
        self.assertIn("SKIP", self.tick_log())
        self.assertNotRegex(self.tick_log(), r"(?m)^\S+ \S+ run: ")  # tick's "run: <reason>" line
        self.assertEqual(self.head(self.remote), self.remote_head)

    def test_fresh_lock_skips_the_tick(self):
        (self.work / ".tmp").mkdir(exist_ok=True)
        lock = self.work / ".tmp/tick.lock"
        lock.write_text("123", encoding="utf-8")
        rc = self.tick("--force", search=[item(1)])
        self.assertEqual(rc, 0, self.dump())
        self.assertIn("another tick is running; skip", self.tick_log())
        self.assertEqual(self.calls(), [])
        self.assertTrue(lock.exists())  # someone else's lock is left alone
        self.assertEqual(self.head(self.remote), self.remote_head)

    def test_stale_lock_older_than_2h_is_taken_over_and_removed(self):
        (self.work / ".tmp").mkdir(exist_ok=True)
        lock = self.work / ".tmp/tick.lock"
        lock.write_text("123", encoding="utf-8")
        old = time.time() - 2 * 3600 - 60
        os.utime(lock, (old, old))
        rc = self.tick("--force", "--no-codex")
        self.assertEqual(rc, 0, self.dump())
        self.assertNotIn("another tick is running", self.tick_log())
        self.assertFalse(lock.exists())
        self.assertNotEqual(self.head(self.remote), self.remote_head)

    def test_no_codex_records_why_and_publishes_without_calling_codex(self):
        rc = self.tick("--force", "--no-codex", search=[item(1)])
        self.assertEqual(rc, 0, self.dump())
        self.assertEqual(self.calls(), [])
        run = self.remote_json("runs")["runs"][0]
        self.assertIn({"source": "search", "error": "Codex 없이 실행 (--no-codex)"}, run["errors"])
        self.assertEqual(self.remote_msg(), "codex: run 2026-10-18 09:05 (+0 new)")

    # BUG (reported, not fixed here): the search step treats *every* uncommitted change in the
    # checkout as a Codex edit and reverts it, so a developer's unsaved work in the same clone is
    # destroyed (happened for real on 2026-10-18 14:09). Fixed: a dirty working tree skips the tick.
    def test_uncommitted_work_present_before_the_tick_is_not_discarded(self):
        p = self.work / "README.md"
        p.write_text(p.read_text(encoding="utf-8") + "\n작업 중\n", encoding="utf-8")
        (self.work / "tests/test_wip.py").write_text("# wip\n", encoding="utf-8")
        self.tick("--force", search=[item(1)])
        self.assertIn("작업 중", p.read_text(encoding="utf-8"))
        self.assertTrue((self.work / "tests/test_wip.py").exists())


if __name__ == "__main__":
    unittest.main()
