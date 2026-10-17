"""PC-side run helper for the Codex app scheduled task (ChatGPT subscription).

The Codex task only does the parts that need judgment (web search, playbook edits);
everything else is one command here. Works with the plain Windows launcher (`py -3`):
it creates .venv on first use and re-runs itself inside it.

  py -3 scripts/local_run.py prepare   git pull --rebase on main, install deps, make .tmp/
  (Codex: web search -> .tmp/search.json)
  py -3 scripts/local_run.py collect   run_deterministic (+ .tmp/search.json), validate, review -> .tmp/review.json
  (Codex: edit data/playbook.md from .tmp/review.json)
  py -3 scripts/local_run.py publish   validate, commit data/ as "codex: run ...", pull --rebase, push main

Notifications are not sent from the PC: the push triggers .github/workflows/notify.yml.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
TMP = ROOT / ".tmp"


def sh(*cmd, check=True, capture=False) -> subprocess.CompletedProcess:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, check=check, env=env,
                          text=True, encoding="utf-8", capture_output=capture)


def ensure_venv() -> None:
    """Re-exec inside .venv (created on first use) so jsonschema etc. are available."""
    if Path(sys.executable).resolve() == VENV_PY.resolve():
        return
    if not VENV_PY.exists():
        print("creating .venv", flush=True)
        venv.create(VENV, with_pip=True)
        sh(VENV_PY, "-m", "pip", "install", "-q", "-r", "requirements.txt")
    sys.exit(subprocess.call([str(VENV_PY), *sys.argv], cwd=ROOT))


def prepare() -> int:
    sh("git", "checkout", "main")
    sh("git", "pull", "--rebase", "--autostash")
    sh(VENV_PY, "-m", "pip", "install", "-q", "-r", "requirements.txt")
    TMP.mkdir(exist_ok=True)
    for stale in ("search.json", "review.json", "validate_failed"):
        (TMP / stale).unlink(missing_ok=True)
    print("ready: write web-search candidates to .tmp/search.json (JSON array)")
    return 0


def collect(search_error: str | None) -> int:
    (TMP / "validate_failed").unlink(missing_ok=True)  # a flag left by an earlier failed day must not leak
    TMP.mkdir(exist_ok=True)
    args = ["scripts/run_deterministic.py"]
    search = TMP / "search.json"
    if search.exists():
        try:
            ok = isinstance(json.loads(search.read_text(encoding="utf-8")), list)
        except ValueError:
            ok = False
        if ok:
            args += ["--extra", str(search)]
        else:
            args += ["--source-error", "search=.tmp/search.json is not a JSON array"]
    if search_error:
        args += ["--source-error", f"search={search_error}"]
    sh(VENV_PY, *args)
    if sh(VENV_PY, "scripts/validate.py", "--record", check=False).returncode != 0:
        print("validate failed: data/feed.json and seen.json will be restored at publish")
        (TMP / "validate_failed").write_text("1", encoding="utf-8")
        return 1
    review = sh(VENV_PY, "scripts/review_run.py", capture=True)
    (TMP / "review.json").write_text(review.stdout, encoding="utf-8")
    print("review written to .tmp/review.json; improve data/playbook.md from its findings (CODEX.md step 6)")
    return 0


def publish() -> int:
    failed = (TMP / "validate_failed").exists()
    if failed:
        sh("git", "checkout", "--", "data/feed.json", "data/seen.json", "data/playbook.md")
    elif sh(VENV_PY, "scripts/validate.py", "--quiet", check=False).returncode != 0:
        print("playbook edit broke validation; restoring it")
        sh("git", "checkout", "--", "data/playbook.md")
    outside = [l for l in sh("git", "status", "--porcelain", capture=True).stdout.splitlines()
               if l[3:] and not l[3:].startswith(("data/", ".tmp/", ".venv/"))]
    if outside:
        print("refusing to publish: changes outside data/:\n" + "\n".join(outside))
        return 1
    sh("git", "add", "data/")
    if sh("git", "diff", "--cached", "--quiet", check=False).returncode == 0:
        print("nothing to commit")
        return 0
    run = json.loads((ROOT / "data/runs.json").read_text(encoding="utf-8"))["runs"][0]
    stamp = run["at"][:16].replace("T", " ")
    msg = f"codex: run {stamp} (+{run['new']} new)" + (" (validate failed)" if failed else "")
    sh("git", "commit", "-q", "-m", msg)
    for _ in range(3):
        if sh("git", "pull", "--rebase", check=False).returncode == 0 and \
                sh("git", "push", "origin", "HEAD:main", check=False).returncode == 0:
            (TMP / "validate_failed").unlink(missing_ok=True)
            errs = ", ".join(f"{e['source']}: {e['error']}" for e in run["errors"]) or "없음"
            print(f"published: 찾은 {run['found']}건, 새 {run['new']}건, 오류: {errs}")
            return 0
    print("push failed")
    return 1


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Korean output on Windows consoles
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", choices=["prepare", "collect", "publish"])
    ap.add_argument("--search-error", help="record why web search could not run")
    args = ap.parse_args()
    ensure_venv()
    return {"prepare": prepare, "collect": lambda: collect(args.search_error),
            "publish": publish}[args.step]()


if __name__ == "__main__":
    sys.exit(main())
