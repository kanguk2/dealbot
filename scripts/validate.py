"""Validate data/ before committing: JSON Schema, cross references, no secrets, playbook shape.

Usage: python scripts/validate.py [--quiet]
Exit code 0 = OK, 1 = problems (printed one per line).
"""
from __future__ import annotations

import argparse
import re
import sys

import common

FILES = ("config", "notifiers", "feed", "seen", "runs", "interests", "links")

# Credential-shaped values are never allowed anywhere in data/.
SECRET_VALUE = re.compile(
    r"hooks\.slack\.com/services|discord(?:app)?\.com/api/webhooks|xox[abprs]-[\w-]{8,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|\b\d{8,10}:AA[\w-]{30,}|Bearer\s+\S{10,}",
    re.I)
# In the hand-edited files, these words should not appear at all (keys or values).
SECRET_WORD = re.compile(r"token|webhook|secret|password|api[_-]?key", re.I)


def _walk(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", k, None
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, None, obj


def secret_problems(name: str, obj) -> list[str]:
    out = []
    strict = name in ("config", "notifiers")
    for path, key, value in _walk(obj):
        text = key if key is not None else value
        if value is not None and SECRET_VALUE.search(value):
            out.append(f"{name}: {path}: looks like a credential; secrets belong in env vars")
        elif strict and SECRET_WORD.search(text):
            out.append(f"{name}: {path}: contains '{SECRET_WORD.search(text).group(0)}'; "
                       "secrets belong in env vars")
    return out


def schema_problems(name: str, obj) -> list[str]:
    from jsonschema import Draft202012Validator
    schema = common.load_json(common.SCHEMAS / f"{name}.schema.json")
    validator = Draft202012Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(obj), key=lambda e: list(e.path)):
        loc = "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in err.path)
        out.append(f"{name}: {loc}: {err.message}")
    return out


def cross_problems(data: dict) -> list[str]:
    out = []
    cfg, nts, feed = data.get("config") or {}, data.get("notifiers") or {}, data.get("feed") or {}
    cat_ids = [c.get("id") for c in cfg.get("categories", [])]
    for dup in {i for i in cat_ids if cat_ids.count(i) > 1}:
        out.append(f"config: duplicate category id '{dup}'")
    feeds = cfg.get("rss_feeds") or {}
    for c in cfg.get("categories", []):
        for s in c.get("sources", []):
            if s.startswith("rss:") and s[4:] not in feeds:
                out.append(f"config: category '{c.get('id')}' uses {s} but rss_feeds has no '{s[4:]}'")
    ch_ids = [c.get("id") for c in nts.get("channels", [])]
    for dup in {i for i in ch_ids if ch_ids.count(i) > 1}:
        out.append(f"notifiers: duplicate channel id '{dup}'")
    item_ids = [it.get("id") for it in feed.get("items", [])]
    for dup in {i for i in item_ids if item_ids.count(i) > 1}:
        out.append(f"feed: duplicate item id '{dup}'")
    limit = cfg.get("feed_limit")
    if limit and len(item_ids) > limit:
        out.append(f"feed: {len(item_ids)} items exceeds feed_limit {limit}")
    return out


def validate() -> list[str]:
    problems, data = [], {}
    for name in FILES:
        path = common.DATA / f"{name}.json"
        try:
            data[name] = common.load_json(path)
        except ValueError as e:
            problems.append(f"{name}: invalid JSON: {e}")
            continue
        if data[name] is None:
            problems.append(f"{name}: missing file data/{path.name}")
            continue
        problems += schema_problems(name, data[name])
        problems += secret_problems(name, data[name])
    problems += cross_problems(data)
    problems += playbook_check()
    return problems


def playbook_check() -> list[str]:
    """data/playbook.md is edited by Codex every run: keep its shape, size and no secrets."""
    from review_run import PLAYBOOK, playbook_problems
    path = common.DATA / PLAYBOOK
    text = path.read_text(encoding="utf-8") if path.exists() else None
    out = playbook_problems(text)
    if text and SECRET_VALUE.search(text):
        out.append("playbook: looks like it contains a credential")
    return out


def main() -> int:
    common.setup_io()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--record", action="store_true",
                    help="on failure, append the problems to the latest run in data/runs.json")
    args = ap.parse_args()
    problems = validate()
    for p in problems:
        print(p)
    if problems and args.record:
        try:
            runs = common.load_data("runs", {"runs": []})
            if runs.get("runs"):
                runs["runs"][0].setdefault("errors", []).append(
                    {"source": "validate", "error": "; ".join(problems)[:500]})
                common.save_data("runs", runs)
        except (ValueError, KeyError, AttributeError, IndexError, TypeError) as e:
            print(f"validate: could not record to runs.json: {e}")
    if not problems and not args.quiet:
        print("validate: OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
