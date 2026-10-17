"""Shared helpers: paths, JSON I/O, time, HTTP. Standard library only."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SCHEMAS = ROOT / "schemas"

USER_AGENT = "dealbot/1.0 (personal)"
RUNS_LIMIT = 50


def setup_io() -> None:
    """Force UTF-8 on stdio so Korean text survives Windows consoles and pipes."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def load_data(name: str, default=None):
    return load_json(DATA / f"{name}.json", default)


def save_data(name: str, obj) -> None:
    save_json(DATA / f"{name}.json", obj)


def read_items(paths: list[str]) -> list[dict]:
    """Read candidate items from files (or stdin for '-' / no paths).

    Accepts a JSON array or an object with an "items" array.
    """
    chunks = []
    if not paths:
        paths = ["-"]
    for p in paths:
        text = sys.stdin.read() if p == "-" else Path(p).read_text(encoding="utf-8")
        text = text.strip()
        if not text:
            continue
        obj = json.loads(text)
        items = obj.get("items", []) if isinstance(obj, dict) else obj
        if not isinstance(items, list):
            raise ValueError(f"{p}: expected a JSON array or {{\"items\": [...]}}")
        chunks.extend(items)
    return chunks


def dump(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


# ---------------------------------------------------------------- time

def tz_for(config: dict | None = None):
    name = ((config or {}).get("schedule") or {}).get("timezone") or "Asia/Seoul"
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        # Windows without tzdata: KST has no DST, so a fixed offset is exact.
        return timezone(timedelta(hours=9), "KST")


def now(config: dict | None = None) -> datetime:
    override = os.environ.get("DEALBOT_NOW")  # for tests: 2026-10-17T09:03:00+09:00
    if override:
        return datetime.fromisoformat(override).astimezone(tz_for(config))
    return datetime.now(tz_for(config)).replace(microsecond=0)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def last_run_at(runs: dict | None) -> datetime | None:
    items = (runs or {}).get("runs") or []
    return parse_dt(items[0]["at"]) if items else None


# ---------------------------------------------------------------- HTTP

class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def http_request(method: str, url: str, *, json_body=None, data: bytes | None = None,
                 form: dict | None = None, headers: dict | None = None,
                 timeout: float = 20) -> bytes:
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
    elif form is not None:
        from urllib.parse import urlencode
        data = urlencode(form).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode("utf-8", "replace").strip()
        # HTML error pages are noise in runs.json; keep short API messages only.
        detail = e.reason if body.startswith("<") or not body else " ".join(body.split())[:150]
        raise HttpError(e.code, str(detail)) from None
    except urllib.error.URLError as e:
        raise HttpError(0, str(e.reason)) from None


def http_get(url: str, **kw) -> bytes:
    return http_request("GET", url, **kw)
