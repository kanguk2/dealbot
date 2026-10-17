"""Did a collection run already happen today (config timezone)? For the Actions fallback job.

Usage: python scripts/ran_today.py   -> prints "yes" or "no" (exit code 0 either way)
"""
from __future__ import annotations

import argparse
import sys

import common


def ran_today(runs: dict, today) -> bool:
    last = common.last_run_at(runs)
    return bool(last) and last.astimezone(today.tzinfo).date() == today.date()


def main() -> int:
    common.setup_io()
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    config = common.load_data("config", {})
    print("yes" if ran_today(common.load_data("runs", {"runs": []}), common.now(config)) else "no")
    return 0


if __name__ == "__main__":
    sys.exit(main())
