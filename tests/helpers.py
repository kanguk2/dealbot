"""Shared test helpers: a scratch data/ dir per test and a way to run the CLI scripts."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

FIXTURES = Path(__file__).parent / "fixtures"


def item(n: int = 1, **over) -> dict:
    """A valid candidate in feed-item shape."""
    base = {"category": "points", "title": f"테스트 적립 이벤트 {n}", "url": f"https://example.com/{n}",
            "source": "search", "price_krw": None, "original_price_krw": None, "discount_pct": None,
            "starts": None, "ends": None, "summary": "요약"}
    base.update(over)
    return base


class DataDirTest(unittest.TestCase):
    """Copies the repo's default data/ into a temp dir; scripts see it via DEALBOT_DATA_DIR."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="dealbot-test-"))
        self.data = self.tmp / "data"
        shutil.copytree(ROOT / "data", self.data)
        # start from an empty history regardless of what is committed in data/
        self.write("feed", {"run_at": None, "items": [], "pending": [], "bought": []})
        self.write("seen", {"keys": {}})
        self.write("runs", {"runs": []})
        self.env = {**os.environ, "DEALBOT_DATA_DIR": str(self.data), "PYTHONIOENCODING": "utf-8"}
        for k in [k for k in self.env if k.startswith("DEALBOT_") and k != "DEALBOT_DATA_DIR"]:
            del self.env[k]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- data helpers
    def read(self, name: str):
        return json.loads((self.data / f"{name}.json").read_text(encoding="utf-8"))

    def write(self, name: str, obj) -> None:
        (self.data / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def edit(self, name: str, fn) -> None:
        obj = self.read(name)
        fn(obj)
        self.write(name, obj)

    def candidates(self, items: list[dict]) -> str:
        path = self.tmp / f"cand-{len(list(self.tmp.glob('cand-*')))}.json"
        path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        return str(path)

    # --- running scripts
    def run_script(self, *args, now: str | None = None, env: dict | None = None, stdin: str | None = None,
                   check: bool = True) -> subprocess.CompletedProcess:
        e = dict(self.env)
        if now:
            e["DEALBOT_NOW"] = now
        e.update(env or {})
        proc = subprocess.run([sys.executable, str(SCRIPTS / args[0]), *args[1:]], input=stdin,
                              capture_output=True, text=True, encoding="utf-8", env=e, cwd=ROOT)
        if check and proc.returncode != 0:
            self.fail(f"{args} exited {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        return proc

    def collect(self, items: list[dict], now: str, *extra_args) -> dict:
        """One run with only the given candidates (no network sources). Returns runs[0]."""
        self.run_script("run_deterministic.py", "--no-sources", "--extra", self.candidates(items),
                        *extra_args, now=now)
        return self.read("runs")["runs"][0]

    def assert_valid(self):
        proc = self.run_script("validate.py", check=False)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
