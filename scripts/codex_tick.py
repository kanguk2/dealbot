"""PC scheduler entry point: run DealBot when due, calling Codex CLI on the ChatGPT subscription.

Windows Task Scheduler runs this every 15 minutes (scripts/install_tick.ps1). Each tick:

  1. local_run.py prepare        -> "SKIP ..." ends the tick here (no Codex usage at all)
  2. codex exec  search.md       -> .tmp/search.json      (web search, live)
  3. local_run.py collect        -> data/, .tmp/review.json
  4. codex exec  review.md       -> data/playbook.md      (only that file is kept)
  5. local_run.py publish        -> "codex: run ..." pushed to main; notify.yml sends alerts

Codex is the bundled CLI of the Codex desktop app (logged in with ChatGPT), found under
%LOCALAPPDATA%/OpenAI/Codex/bin/*/codex.exe, or DEALBOT_CODEX. Log: .tmp/tick.log.

  py -3 scripts/codex_tick.py            # what the scheduler runs
  py -3 scripts/codex_tick.py --force    # run now even if nothing is due
  py -3 scripts/codex_tick.py --no-codex # deterministic sources only (no search/learning)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".tmp"
LOCK = TMP / "tick.lock"
LOG = TMP / "tick.log"
LOCK_STALE_S = 2 * 3600
CODEX_TIMEOUT_S = 25 * 60
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # no console flashes from the scheduler


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    TMP.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    if LOG.stat().st_size > 512_000:  # keep the log small
        LOG.write_text(LOG.read_text(encoding="utf-8")[-256_000:], encoding="utf-8")


def run(cmd: list, timeout: int | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, env=env, text=True, encoding="utf-8",
                          errors="replace", capture_output=True, timeout=timeout,
                          creationflags=NO_WINDOW)


def find_codex() -> str | None:
    if os.environ.get("DEALBOT_CODEX"):
        return os.environ["DEALBOT_CODEX"]
    base = os.environ.get("LOCALAPPDATA", "")
    found = glob.glob(os.path.join(base, "OpenAI", "Codex", "bin", "*", "codex.exe"))
    found += [p for p in (shutil.which("codex"),) if p]
    return max(found, key=os.path.getmtime) if found else None  # app updates add a new folder


def local_run(step: str, *extra) -> subprocess.CompletedProcess:
    proc = run([sys.executable, "scripts/local_run.py", step, *extra])
    for line in (proc.stdout + proc.stderr).strip().splitlines()[-6:]:
        log(f"  [{step}] {line}")
    return proc


def codex(prompt_file: str, out_file: str, search: bool) -> bool:
    exe = find_codex()
    if not exe:
        log("  codex.exe not found (Codex desktop app installed?)")
        return False
    cmd = [exe, "exec", "--ephemeral", "-C", ROOT, "-s", "workspace-write", "-o", TMP / out_file]
    if search:
        cmd += ["-c", 'web_search="live"']
    cmd.append((ROOT / prompt_file).read_text(encoding="utf-8"))
    try:
        proc = run(cmd, timeout=CODEX_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log(f"  codex timed out after {CODEX_TIMEOUT_S // 60} min ({prompt_file})")
        return False
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    log(f"  codex {Path(prompt_file).stem}: exit {proc.returncode} · " + " / ".join(tail)[:300])
    return proc.returncode == 0


def tracked_changes(allowed: tuple[str, ...]) -> list[str]:
    out = run(["git", "status", "--porcelain"]).stdout.splitlines()
    return [l[3:] for l in out if l[3:] and not l[3:].startswith(allowed)]


def restore(paths: list[str]) -> None:
    for p in paths:
        if run(["git", "ls-files", "--error-unmatch", p]).returncode == 0:
            run(["git", "checkout", "--", p])
        else:
            Path(ROOT / p).unlink(missing_ok=True)


def tick(force: bool, use_codex: bool) -> int:
    prep = local_run("prepare", *(["--force"] if force else []))
    last = (prep.stdout.strip().splitlines() or [""])[-1]
    if prep.returncode != 0:
        log("prepare failed")
        return 1
    if last.startswith("SKIP"):
        return 0
    log(f"run: {last}")

    search_error = None
    if use_codex:
        ok = codex(".github/codex/search.md", "search-report.txt", search=True)
        stray = tracked_changes((".tmp/", ".venv/"))  # search may only write .tmp/search.json
        if stray:
            log(f"  discarding Codex edits outside .tmp/: {stray}")
            restore(stray)
        if not ok and not (TMP / "search.json").exists():
            search_error = "Codex 검색 실행 실패 (.tmp/tick.log)"
    else:
        search_error = "Codex 없이 실행 (--no-codex)"

    if local_run("collect", *(["--search-error", search_error] if search_error else [])).returncode != 0:
        return local_run("publish").returncode  # publishes the run with the validate error recorded

    if use_codex:
        snap = {p: p.read_bytes() for p in (ROOT / "data").glob("*.json")}  # script output
        codex(".github/codex/review.md", "review-report.txt", search=False)
        stray = tracked_changes((".tmp/", ".venv/", "data/"))
        if stray:
            log(f"  discarding Codex edits outside data/: {stray}")
            restore(stray)
        for path, data in snap.items():  # only data/playbook.md may change in review
            path.write_bytes(data)

    return local_run("publish").returncode


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="run even if nothing is due")
    ap.add_argument("--no-codex", action="store_true", help="skip web search and playbook learning")
    args = ap.parse_args()

    TMP.mkdir(exist_ok=True)
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < LOCK_STALE_S:
        log("another tick is running; skip")
        return 0
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    try:
        return tick(args.force, not args.no_codex)
    except Exception as e:  # noqa: BLE001 - the scheduler shows nothing; leave a trace
        log(f"tick crashed: {e!r}")
        return 1
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
