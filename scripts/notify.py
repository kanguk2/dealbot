"""Send feed items to the channels in data/notifiers.json.

Modes:
  --since-run      Send what is due from data/feed.json and record results (spec step 7):
                     instant -> new items, held back during quiet_hours
                     daily   -> items found before today (sent at the first run of the day)
                     weekly  -> items found before this Monday (first run of the week)
                   Results go to feed item "notified" and the latest data/runs.json entry.
                   Also sends the "source failed 3 times in a row" alert (once a day).
  (stdin)          Items piped in (e.g. from dedupe.py) are sent by category priority.
  --sample         Use built-in sample items.
  --health-alert   Send "딜봇이 N시간째 실행되지 않음" to every enabled channel.

Options:
  --dry-run        Print each channel's payload instead of sending. Writes nothing.
  --channel ID     Only this channel (id or type). With --sample, sends one real test message.

Examples:
  python scripts/sources/rss.py | python scripts/dedupe.py | python scripts/notify.py --dry-run
  python scripts/notify.py --dry-run --sample
  python scripts/notify.py --sample --channel ntfy
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta

import common
from notifiers.base import Notifier, SendResult, load_plugins

SAMPLE_ITEMS = [
    {"id": "sample0001", "key": "points|sample1|", "category": "points",
     "title": "[KB Pay] 10월 결제 이벤트 최대 1만 포인트 적립", "url": "https://example.com/kbpay",
     "source": "rss:ppomppu_coupon", "price_krw": None, "original_price_krw": None,
     "discount_pct": None, "starts": "2026-10-16", "ends": "2026-10-31",
     "found_at": "2026-10-17T09:03:00+09:00", "summary": "KB Pay 결제 3회 이상 시 응모. 선착순 아님.",
     "notified": [], "status": "new"},
    {"id": "sample0002", "key": "points|sample2|0", "category": "points",
     "title": "네이버페이 출석 체크 이벤트 매일 10원", "url": "https://example.com/npay",
     "source": "search", "price_krw": 0, "original_price_krw": None, "discount_pct": None,
     "starts": None, "ends": None, "found_at": "2026-10-17T09:03:00+09:00",
     "summary": None, "notified": [], "status": "new"},
]


# ---------------------------------------------------------------- scheduling rules

def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def in_quiet_hours(now: datetime, quiet: dict | None) -> bool:
    if not quiet or not quiet.get("start") or not quiet.get("end"):
        return False
    cur, start, end = (now.hour, now.minute), _hm(quiet["start"]), _hm(quiet["end"])
    if start == end:
        return False
    return start <= cur < end if start < end else (cur >= start or cur < end)


def window(priority: str, now: datetime) -> tuple[datetime, datetime]:
    """found_at range [lo, hi) whose items are due for this priority right now."""
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if priority == "instant":
        return now - timedelta(hours=48), now + timedelta(minutes=1)
    if priority == "daily":
        return day_start - timedelta(days=8), day_start
    monday = day_start - timedelta(days=now.weekday())  # weekly
    return monday - timedelta(days=14), monday


def due_items(items: list[dict], priority: str, channel_id: str, now: datetime,
              config: dict, cat_priority: dict) -> list[dict]:
    """Items of this priority that this channel has not received and are due now."""
    if priority == "instant" and in_quiet_hours(now, config.get("quiet_hours")):
        return []
    lo, hi = window(priority, now)
    out = []
    for it in items:
        if cat_priority.get(it.get("category")) != priority or it.get("status") == "ignored":
            continue
        if channel_id in (it.get("notified") or []):
            continue
        ends = common.parse_date(it.get("ends"))
        if ends and ends < now.date():  # ended while waiting for a digest
            continue
        found = common.parse_dt(it.get("found_at"))
        if found and lo <= found < hi:
            out.append(it)
    return out


# ---------------------------------------------------------------- channel setup

def build_channels(notifiers: dict, config: dict, now: datetime, dry_run: bool,
                   only: str | None, include_disabled: bool = False) -> list[Notifier]:
    plugins = load_plugins()
    fmt = notifiers.get("format") or {}
    ctx = {"now": now,
           "category_names": {c["id"]: c.get("name", c["id"]) for c in config.get("categories", [])}}
    out = []
    for ch in notifiers.get("channels", []):
        if only and only not in (ch.get("id"), ch.get("type")):
            continue
        if not ch.get("enabled") and not (include_disabled or only):
            continue
        cls = plugins.get(ch.get("type"))
        if cls is None:
            print(f"notify: unknown channel type {ch.get('type')!r}", file=sys.stderr)
            continue
        out.append(cls(ch, fmt, ctx, dry_run=dry_run))
    return out


def broadcast(channels: list[Notifier], title: str, body: str,
              skip: str | None = None) -> list[dict]:
    errors = []
    for n in channels:
        if n.channel.get("id") == skip:
            continue
        res = n.send_text(title, body)
        if not res.ok:
            errors.append({"source": f"notify:{n.channel.get('id')}", "error": res.error})
    return errors


def _send(n: Notifier, items: list[dict], priority: str) -> tuple[SendResult, str | None]:
    """Returns (result, kakao_token_error)."""
    try:
        return n.send(items, priority), None
    except Exception as e:  # noqa: BLE001 - token refresh failures surface here
        if type(e).__name__ == "KakaoTokenError":
            return SendResult(ok=False, error=str(e)), str(e)
        return SendResult(ok=False, error=str(e)[:300]), None


# ---------------------------------------------------------------- modes

def prune_pending(pending: list[dict], notifiers: dict, cat_priority: dict, now: datetime) -> list[dict]:
    """Drop queue entries every interested channel has received, or that aged out of their window."""
    keep = []
    for it in pending:
        prio = cat_priority.get(it.get("category"))
        wanted = {c["id"] for c in notifiers.get("channels", [])
                  if c.get("enabled") and prio in c.get("priorities", [])}
        found = common.parse_dt(it.get("found_at"))
        if prio is None or it.get("status") == "ignored" or wanted <= set(it.get("notified", [])):
            continue
        if found and found < window(prio, now)[0]:
            continue
        keep.append(it)
    return keep


def run_since(args, config, notifiers, now) -> int:
    from run_deterministic import load_feed
    feed = load_feed()
    runs = common.load_data("runs", {"runs": []})
    cat_priority = {c["id"]: c.get("priority", "instant") for c in config.get("categories", [])}
    channels = build_channels(notifiers, config, now, args.dry_run, args.channel)
    # Send from the queue: the page feed is replaced every run, the queue keeps digests alive.
    shown = {it["id"]: it for it in feed["items"]}
    items = feed["pending"]
    for it in items:  # 무시 on the page also stops pending notifications
        if it["id"] in shown:
            it["status"] = shown[it["id"]]["status"]
    errors, alerts, notified_ids = [], [], set()
    kakao_error = None

    for n in channels:
        cid = n.channel["id"]
        for priority in n.channel.get("priorities", []):
            batch = due_items(items, priority, cid, now, config, cat_priority)
            if not batch:
                continue
            res, kerr = _send(n, batch, priority)
            kakao_error = kakao_error or kerr
            sent = {it["id"] for it in batch} if res.ok else set(res.item_ids)
            for it in batch:
                if it["id"] in sent:
                    for copy_ in (it, shown.get(it["id"])):  # queue entry and page entry
                        if copy_ is not None and cid not in copy_["notified"]:
                            copy_["notified"].append(cid)
            notified_ids |= sent
            print(f"notify: {cid} {priority}: {len(sent)}/{len(batch)} items, "
                  f"{res.messages} messages{'' if res.ok else ' ERROR ' + str(res.error)}")
            if not res.ok:
                errors.append({"source": f"notify:{cid}", "error": res.error})

    latest = (runs.get("runs") or [None])[0]
    today = now.date().isoformat()
    sent_today = {a for r in runs.get("runs", []) if r["at"][:10] == today for a in r.get("alerts", [])}

    # Same source failing in the last 3 runs -> one alert per day.
    recent = runs.get("runs", [])[:3]
    if len(recent) == 3:
        failing = set.intersection(*({e["source"] for e in r.get("errors", [])
                                      if not e["source"].startswith("notify:")} for r in recent))
        for src in sorted(failing):
            key = f"source_fail:{src}"
            if key not in sent_today:
                last = next(e["error"] for e in recent[0]["errors"] if e["source"] == src)
                errors += broadcast(channels, "[딜봇] 소스 실패", f"소스 {src} 3회 연속 실패: {last}")
                alerts.append(key)

    if kakao_error and "kakao_token" not in sent_today:
        others = [c for c in channels if c.type != "kakao"]
        errors += broadcast(others, "[딜봇] 카카오 토큰 갱신 필요",
                            f"{kakao_error}\nREADME의 카카오 토큰 발급 절차로 DEALBOT_KAKAO_REFRESH_TOKEN을 새로 넣으세요.")
        alerts.append("kakao_token")

    print(f"notify: {len(notified_ids)} items sent, {len(errors)} errors")
    if args.dry_run:
        return 0
    feed["pending"] = prune_pending(feed["pending"], notifiers, cat_priority, now)
    common.save_data("feed", feed)
    if latest is not None:
        latest["notified"] = latest.get("notified", 0) + len(notified_ids)
        latest.setdefault("errors", []).extend(errors)
        if alerts:
            latest["alerts"] = sorted(set(latest.get("alerts", [])) | set(alerts))
        common.save_data("runs", runs)
    return 0


def run_items(args, config, notifiers, now, items) -> int:
    """Send the given items (stdin / --sample) by priority; never writes data/."""
    cat_priority = {c["id"]: c.get("priority", "instant") for c in config.get("categories", [])}
    channels = build_channels(notifiers, config, now, args.dry_run, args.channel,
                              include_disabled=args.sample and args.dry_run)
    if not channels:
        print("notify: no enabled channels (data/notifiers.json)", file=sys.stderr)
    failed = 0
    for n in channels:
        if args.sample:  # show/test every channel regardless of its priorities
            groups = [("instant", items)]
        else:
            groups = [(p, [it for it in items if cat_priority.get(it.get("category"), "instant") == p])
                      for p in ("instant", "daily", "weekly") if p in n.channel.get("priorities", [])]
        for priority, batch in groups:
            if not batch:
                continue
            res, _ = _send(n, batch, priority)
            if not args.dry_run:
                print(f"notify: {n.channel['id']}: {'ok' if res.ok else 'ERROR ' + str(res.error)}")
            failed += not res.ok
    return 1 if failed else 0


def run_health(args, config, notifiers, now) -> int:
    runs = common.load_data("runs", {"runs": []})
    last = common.last_run_at(runs)
    hours = int((now - last).total_seconds() // 3600) if last else None
    title = "[딜봇] 실행 멈춤 감지"
    body = (f"딜봇이 {hours}시간째 실행되지 않음 (마지막 실행 {last:%m/%d %H:%M})" if last
            else "딜봇 실행 기록이 없습니다 (data/runs.json 비어 있음)")
    recent = [f"{e['source']}: {e['error']}" for r in runs.get("runs", [])[:3] for e in r.get("errors", [])]
    if recent:
        body += "\n최근 오류: " + " / ".join(recent[:3])
    channels = build_channels(notifiers, config, now, args.dry_run, args.channel)
    errors = broadcast(channels, title, body)
    for e in errors:
        print(f"notify: {e['source']}: {e['error']}", file=sys.stderr)
    return 1 if errors and len(errors) == len(channels) else 0


def main() -> int:
    common.setup_io()
    ap = argparse.ArgumentParser(description="send deals to notification channels",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("Examples:")[1])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--since-run", action="store_true", help="send what is due from feed.json")
    mode.add_argument("--sample", action="store_true", help="use built-in sample items")
    mode.add_argument("--health-alert", action="store_true", help="send the bot-stalled alert")
    ap.add_argument("--dry-run", action="store_true", help="print payloads, send/write nothing")
    ap.add_argument("--channel", help="only this channel id or type")
    args = ap.parse_args()

    config = common.load_data("config", {})
    notifiers = common.load_data("notifiers", {"channels": []})
    now = common.now(config)

    if args.since_run:
        return run_since(args, config, notifiers, now)
    if args.health_alert:
        return run_health(args, config, notifiers, now)
    if args.sample:
        # A real test send (--channel without --dry-run) posts just one sample item.
        live_test = args.channel and not args.dry_run
        return run_items(args, config, notifiers, now, SAMPLE_ITEMS[:1] if live_test else SAMPLE_ITEMS)
    if sys.stdin.isatty():
        ap.error("pipe items on stdin, or use --since-run / --sample / --health-alert")
    return run_items(args, config, notifiers, now, common.read_items(["-"]))


if __name__ == "__main__":
    sys.exit(main())
