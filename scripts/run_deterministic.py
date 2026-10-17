"""One collection run: sources -> dedupe -> filter -> feed/seen/runs (spec steps 2-5).

Runs every script-backed source used by an enabled category, merges extra candidate
files (Codex's web-search results), and records the run in data/runs.json.
It does not validate, notify or commit; those are separate steps.

Usage:
  python scripts/run_deterministic.py
  python scripts/run_deterministic.py --extra .tmp/search.json --source-error "search=timeout"
  python scripts/run_deterministic.py --dry-run     # print what would be added, write nothing
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

import common
import dedupe
import filters
from sources import enabled_sources, fetch_source


def collect(config: dict, since) -> tuple[list[dict], list[dict]]:
    items, errors = [], []
    for src in enabled_sources(config):
        try:
            got = fetch_source(config, src, since=since)
            items.extend(got)
            print(f"{src}: {len(got)} candidates", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - one bad source must not stop the run
            errors.append({"source": src, "error": str(e)[:300]})
            print(f"{src}: FAILED {e}", file=sys.stderr)
    return items, errors


def ingest(new_items: list[dict], config: dict, run_at, run_errors: list[dict],
           found: int, by_source: dict) -> dict:
    """Prepend items to feed, remember keys, append the run record. Returns the run."""
    feed = common.load_data("feed", {"items": []})
    seen = common.load_data("seen", {"keys": {}})
    runs = common.load_data("runs", {"runs": []})
    stamp = run_at.isoformat()
    added = [{**it, "found_at": stamp, "notified": [], "status": "new"} for it in new_items]
    feed["items"] = (added + feed.get("items", []))[: config.get("feed_limit", 500)]
    dedupe.prune(seen, config.get("seen_ttl_days", 30), run_at.date())
    dedupe.remember(seen, added, run_at.date())
    run = {"at": stamp, "found": found, "new": len(added), "notified": 0,
           "errors": run_errors, "by_source": by_source}
    runs["runs"] = ([run] + runs.get("runs", []))[: common.RUNS_LIMIT]
    common.save_data("feed", feed)
    common.save_data("seen", seen)
    common.save_data("runs", runs)
    return run


def main() -> int:
    common.setup_io()
    ap = argparse.ArgumentParser(description="collect -> dedupe -> filter -> data/")
    ap.add_argument("--extra", action="append", default=[], metavar="FILE",
                    help="extra candidate JSON (e.g. Codex search results); repeatable")
    ap.add_argument("--source-error", action="append", default=[], metavar="NAME=MSG",
                    help="record a failure that happened outside this script; repeatable")
    ap.add_argument("--no-sources", action="store_true", help="skip script sources")
    ap.add_argument("--dry-run", action="store_true", help="print result, write nothing")
    args = ap.parse_args()

    config = common.load_data("config", {})
    run_at = common.now(config)
    since = common.last_run_at(common.load_data("runs", {}))

    candidates, errors = ([], []) if args.no_sources else collect(config, since)
    if args.extra:
        try:
            candidates.extend(common.read_items(args.extra))
        except Exception as e:  # noqa: BLE001
            errors.append({"source": "search", "error": f"bad candidate file: {e}"[:300]})
    for spec in args.source_error:
        name, _, msg = spec.partition("=")
        errors.append({"source": name.strip() or "unknown", "error": msg.strip()[:300]})

    by_source = dict(Counter(c.get("source") or "search" for c in candidates))
    seen = common.load_data("seen", {"keys": {}})
    new, rejected = dedupe.dedupe(candidates, config, seen)
    for title, reason in rejected:
        print(f"dedupe: skipped {title!r}: {reason}", file=sys.stderr)
    kept, dropped = filters.apply(new, config, run_at.date())
    for title, why in dropped:
        print(f"filter: dropped {title!r}: {why}", file=sys.stderr)

    if args.dry_run:
        common.dump({"found": len(candidates), "new": kept, "errors": errors,
                     "by_source": by_source})
        return 0
    run = ingest(kept, config, run_at, errors, len(candidates), by_source)
    print(f"run {run['at']}: found {run['found']}, new {run['new']}, "
          f"errors {len(run['errors'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
