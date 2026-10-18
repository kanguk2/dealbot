"""Is a collection run due? Every config.schedule.interval_hours, or when the page asked for one.

  python scripts/due.py                         # PC check (Codex app task polls often)
  python scripts/due.py --slack 3 --request-wait 2   # Actions fallback: only if the PC missed it

Prints "yes <reason>" or "no <reason>" (exit code 0 either way).

  interval: due when the last run is older than interval_hours - 1 (polling drift tolerance) + slack
  request:  due when an open request in data/requests.json is older than request-wait hours
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

import common

DRIFT_HOURS = 1  # the PC polls about hourly; don't push each day's run an hour later


def _aware(dt: datetime | None, tz) -> datetime | None:
    """A hand-edited requested_at without an offset is read in the config timezone."""
    return dt.replace(tzinfo=tz) if dt is not None and dt.tzinfo is None else dt


def open_requests(requests: dict | None) -> list[dict]:
    return [r for r in (requests or {}).get("requests", []) if r.get("status") == "open"]


def is_due(runs: dict, requests: dict, now: datetime, interval_hours: int,
           slack_hours: float = 0, request_wait_hours: float = 0) -> tuple[bool, str]:
    for r in open_requests(requests):
        at = _aware(common.parse_dt(r.get("requested_at")), now.tzinfo)
        if at and now - at >= timedelta(hours=request_wait_hours):
            return True, f"페이지 요청 {at:%m/%d %H:%M}"
    last = common.last_run_at(runs)
    if last is None:
        return True, "실행 기록 없음"
    wait = timedelta(hours=max(0, interval_hours - DRIFT_HOURS) + slack_hours)
    if now - last >= wait:
        return True, f"마지막 실행 {last:%m/%d %H:%M} 이후 {int((now - last).total_seconds() // 3600)}시간"
    left = wait - (now - last)
    return False, f"다음 자동 실행까지 약 {int(left.total_seconds() // 3600)}시간, 열린 요청 없음"


def close_requests(requests: dict, run_at: datetime) -> int:
    """Mark requests made before this run as done. Returns how many were closed."""
    n = 0
    for r in open_requests(requests):
        at = _aware(common.parse_dt(r.get("requested_at")), run_at.tzinfo)
        if at is None or at <= run_at:
            r["status"], r["done_at"] = "done", run_at.isoformat()
            n += 1
    requests["requests"] = requests.get("requests", [])[-50:]
    return n


def main() -> int:
    common.setup_io()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--slack", type=float, default=0, help="extra hours before an interval run is due")
    ap.add_argument("--request-wait", type=float, default=0, help="hours an open request may wait")
    args = ap.parse_args()
    config = common.load_data("config", {})
    interval = int((config.get("schedule") or {}).get("interval_hours", 24))
    due, why = is_due(common.load_data("runs", {"runs": []}), common.load_data("requests", {"requests": []}),
                      common.now(config), interval, args.slack, args.request_wait)
    print(f"{'yes' if due else 'no'} {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
