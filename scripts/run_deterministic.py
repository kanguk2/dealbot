"""One collection run: sources -> dedupe -> filter -> feed/seen/runs (spec steps 2-5).

Runs every script-backed source used by an enabled category, merges extra candidate
files (Codex's web-search results), and records the run in data/runs.json.
The page feed (feed.items) is replaced by this run's new deals every time; see replace_feed.
It does not validate, notify or commit; those are separate steps.

Usage:
  python scripts/run_deterministic.py
  python scripts/run_deterministic.py --extra .tmp/search.json --source-error "search=timeout"
  python scripts/run_deterministic.py --dry-run     # print what would be added, write nothing
"""
from __future__ import annotations

import argparse
import copy
import sys
from collections import Counter
from datetime import timedelta

import common
import dedupe
import due
import filters
from sources import enabled_sources, fetch_source

BOUGHT_LIMIT = 200
RECENT_LIMIT = 60  # pool for the page's 대표/관심 딜 picks, so a quiet run still has something to show
PENDING_DAYS = 22  # longest notify window (weekly: up to 21 days back) + 1
FEEDBACK_LIMIT = 20
SAMPLE_LIMIT = 10

# filters/dedupe reason text -> stable code for runs.json "dropped" (read by review_run.py)
REASON_CODES = (("exclude word", "exclude"), ("no keyword", "no_keyword"), ("discount", "low_discount"),
                ("price", "over_price"), ("ended", "ended"), ("less than", "too_close"),
                ("unknown or disabled category", "bad_category"), ("unknown category", "bad_category"),
                ("title missing", "invalid"), ("bad url", "invalid"))


def reason_code(why: str) -> str:
    return next((code for text, code in REASON_CODES if text in why), "other")


def drop_report(candidates: list[dict], new: list[dict], rejected: list, dropped: list) -> tuple[dict, list]:
    """Counts per drop reason plus a few examples, search results first (they teach the playbook)."""
    counts = Counter(reason_code(why) for _, why in rejected + dropped)
    seen_dupes = len(candidates) - len(new) - len(rejected)
    if seen_dupes:
        counts["already_seen"] = seen_dupes
    samples = sorted(rejected + dropped, key=lambda x: (x[0].get("source") or "search") != "search")
    return dict(counts), [{"title": (it.get("title") or "")[:80], "source": it.get("source") or "search",
                           "reason": why[:80]} for it, why in samples[:SAMPLE_LIMIT]]


NEW_SOURCE_LOOKBACK_HOURS = 48


def source_since(src: str, runs: dict, since, run_at):
    """Cutoff per source: the last run, or a 48h lookback for a source no recent run has used
    (a newly added RSS feed would otherwise start empty)."""
    used = any(src in (r.get("by_source") or {}) or any(e.get("source") == src for e in r.get("errors", []))
               for r in (runs or {}).get("runs", [])[:10])
    if used and since is not None:
        return since
    return run_at - timedelta(hours=NEW_SOURCE_LOOKBACK_HOURS)


def collect(config: dict, since, runs: dict | None = None, run_at=None) -> tuple[list[dict], list[dict]]:
    items, errors = [], []
    for src in enabled_sources(config):
        try:
            cutoff = source_since(src, runs, since, run_at) if run_at is not None else since
            got = fetch_source(config, src, since=cutoff)
            items.extend(got)
            print(f"{src}: {len(got)} candidates", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - one bad source must not stop the run
            errors.append({"source": src, "error": str(e)[:300]})
            print(f"{src}: FAILED {e}", file=sys.stderr)
    return items, errors


def empty_feed() -> dict:
    return {"run_at": None, "items": [], "pending": [], "bought": [], "recent": []}


def load_feed() -> dict:
    return {**empty_feed(), **common.load_data("feed", empty_feed())}


def replace_feed(feed: dict, added: list[dict], run_at, feed_limit: int) -> dict:
    """The page shows only this run's results; earlier ones are dropped.
    Returns what the user marked on the replaced page (feedback for review_run.py).

    - items:   replaced by this run's new deals
    - pending: notification queue, so daily/weekly digests survive the replacement
    - bought:  deals marked 샀음 on the page are kept for the monthly stats
    - recent:  rolling pool of still-open deals from recent runs (대표/관심 딜 picks)
    """
    feedback = {s: [{"title": it["title"][:80], "source": it["source"], "url": it["url"]}
                    for it in feed["items"] if it.get("status") == s][:FEEDBACK_LIMIT]
                for s in ("ignored", "bought")}
    # The page is about to be replaced: carry its 무시/샀음 marks into the queue first,
    # otherwise an ignored deal would still go out in the next digest.
    marks = {it["id"]: it.get("status") for it in feed["items"]}
    for p in feed["pending"]:
        if marks.get(p["id"]) in ("ignored", "bought"):
            p["status"] = marks[p["id"]]
    known = {b["id"] for b in feed["bought"]}
    carried = [it for it in feed["items"] if it.get("status") == "bought" and it["id"] not in known]
    feed["bought"] = (carried + feed["bought"])[:BOUGHT_LIMIT]
    feed["items"] = added[:feed_limit]
    feed["run_at"] = run_at.isoformat()
    cutoff = run_at - timedelta(days=PENDING_DAYS)
    kept = [p for p in feed["pending"]
            if (common.parse_dt(p.get("found_at")) or run_at) >= cutoff]
    feed["pending"] = [copy.deepcopy(it) for it in added] + kept
    today = run_at.date().isoformat()
    pool, ids = [], set()
    for it in [copy.deepcopy(a) for a in added] + feed["recent"]:
        status = marks.get(it["id"], it.get("status", "new"))  # the page's mark wins
        ignored = "ignored" in (status, it.get("status"))  # ignored on the page or earlier in the pool
        if it["id"] in ids or (it.get("ends") and it["ends"] < today) or ignored:
            continue
        ids.add(it["id"])
        pool.append({**it, "status": status})
    feed["recent"] = pool[:RECENT_LIMIT]
    return feedback


def ingest(new_items: list[dict], config: dict, run_at, run_errors: list[dict],
           found: int, by_source: dict, dropped: dict | None = None,
           drop_samples: list | None = None) -> dict:
    """Replace the feed with this run, remember keys, append the run record. Returns the run."""
    feed = load_feed()
    seen = common.load_data("seen", {"keys": {}})
    runs = common.load_data("runs", {"runs": []})
    stamp = run_at.isoformat()
    added = [{**it, "found_at": stamp, "notified": [], "status": "new"} for it in new_items]
    feedback = replace_feed(feed, added, run_at, config.get("feed_limit", 500))
    dedupe.prune(seen, config.get("seen_ttl_days", 30), run_at.date())
    dedupe.remember(seen, added, run_at.date())
    run = {"at": stamp, "found": found, "new": len(added), "notified": 0,
           "errors": run_errors, "by_source": by_source,
           "dropped": dropped or {}, "drop_samples": drop_samples or [], "user_feedback": feedback}
    runs["runs"] = ([run] + runs.get("runs", []))[: common.RUNS_LIMIT]
    common.save_data("feed", feed)
    common.save_data("seen", seen)
    common.save_data("runs", runs)
    requests = common.load_data("requests")
    if requests is not None and due.close_requests(requests, run_at):  # this run answers 지금 새로 찾기
        common.save_data("requests", requests)
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

    runs_log = common.load_data("runs", {"runs": []})
    candidates, errors = ([], []) if args.no_sources else collect(config, since, runs_log, run_at)
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
    for raw, reason in rejected:
        print(f"dedupe: skipped {raw.get('title')!r}: {reason}", file=sys.stderr)
    kept, dropped = filters.apply(new, config, run_at.date())
    for it, why in dropped:
        print(f"filter: dropped {it.get('title')!r}: {why}", file=sys.stderr)
    drop_counts, drop_samples = drop_report(candidates, new, rejected, dropped)

    if args.dry_run:
        common.dump({"found": len(candidates), "new": kept, "errors": errors,
                     "by_source": by_source, "dropped": drop_counts, "drop_samples": drop_samples})
        return 0
    run = ingest(kept, config, run_at, errors, len(candidates), by_source, drop_counts, drop_samples)
    print(f"run {run['at']}: found {run['found']}, new {run['new']}, "
          f"errors {len(run['errors'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
