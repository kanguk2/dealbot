"""Review the latest run for search-quality problems (CODEX.md step 7).

Deterministic: reads data/runs.json, feed.json and config.json and reports what went
wrong or right, with a hint per finding. Codex uses the report to improve
data/playbook.md so the next run searches better. It never edits files itself.

Usage: python scripts/review_run.py > .tmp/review.json
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from urllib.parse import urlparse

import common
from run_deterministic import load_feed, reason_code

PLAYBOOK = "playbook.md"
PLAYBOOK_LIMIT = 12000
PLAYBOOK_SECTIONS = ("## 검색어", "## 우선 출처", "## 피할 출처·패턴", "## 판단 기준",
                     "## 최근 교훈", "## 변경 이력")


def finding(kind: str, detail: str, hint: str, evidence=None) -> dict:
    out = {"type": kind, "detail": detail, "hint": hint}
    if evidence:
        out["evidence"] = evidence
    return out


def review(config: dict, runs: dict, feed: dict) -> dict:
    history = runs.get("runs") or []
    if not history:
        return {"run": None, "findings": [finding(
            "no_run", "실행 기록이 없다", "먼저 3단계를 실행한다")]}
    run = history[0]
    search_cats = [c["id"] for c in config.get("categories", [])
                   if c.get("enabled") and "search" in c.get("sources", [])]
    items = feed.get("items") or []
    search_items = [i for i in items if i.get("source") == "search"]
    dropped = run.get("dropped") or {}
    samples = run.get("drop_samples") or []
    search_samples = [s for s in samples if s["source"] == "search"]
    found_search = (run.get("by_source") or {}).get("search", 0)
    out = []

    # --- search volume
    if search_cats and found_search == 0 and not any(e["source"] == "search" for e in run.get("errors", [])):
        out.append(finding("search_empty", f"검색 카테고리 {search_cats}에서 후보 0건",
                           "검색어가 너무 좁거나 기준 시각 이후 글이 없다. ## 검색어에 더 넓은 검색어를 하나 추가해 본다"))
    if found_search and not search_items:
        out.append(finding("search_all_dropped", f"검색 후보 {found_search}건이 전부 걸러졌다",
                           "아래 drop 사유를 보고 ## 판단 기준이나 ## 검색어를 고친다", search_samples))

    # --- why things were dropped
    for code, hint in (
        ("ended", "이미 끝난 이벤트를 후보로 냈다. 검색 단계에서 기한을 먼저 확인하는 규칙을 ## 판단 기준에 넣는다"),
        ("too_close", "마감이 너무 가까운 이벤트를 냈다. min_days_left를 검색 단계에서 지키도록 강조한다"),
        ("exclude", "제외어가 들어간 결과를 냈다. 그 패턴을 ## 피할 출처·패턴에 적는다"),
        ("invalid", "제목이나 URL이 빠진 후보를 냈다. 후보 형식을 지킨다"),
        ("bad_category", "config에 없는 카테고리 id를 썼다. 카테고리 id를 그대로 쓴다"),
        ("already_seen", "이미 잡았던 딜을 다시 냈다. 기준 시각 이후 글만 고르는지 확인한다"),
    ):
        n = dropped.get(code, 0)
        if n:
            ev = [s for s in samples if reason_code(s["reason"]) == code]
            out.append(finding(f"dropped_{code}", f"{n}건이 '{code}' 사유로 빠졌다", hint, ev[:5] or None))

    # --- quality of what was kept
    no_ends = [i["title"][:60] for i in search_items if not i.get("ends")]
    if search_items and len(no_ends) * 2 > len(search_items):
        out.append(finding("missing_ends", f"검색 결과 {len(search_items)}건 중 {len(no_ends)}건이 기한 없음",
                           "기한이 적힌 공식 페이지나 본문을 열어 확인하도록 ## 우선 출처·## 판단 기준을 보강한다",
                           no_ends[:5]))
    no_summary = [i["title"][:60] for i in search_items if not i.get("summary")]
    if search_items and len(no_summary) * 2 > len(search_items):
        out.append(finding("missing_summary", f"검색 결과 {len(no_summary)}건에 요약 없음",
                           "응모 조건·대상을 summary에 적도록 ## 판단 기준을 보강한다", no_summary[:5]))
    domains = Counter(urlparse(i["url"]).netloc for i in search_items)
    if domains:
        out.append(finding("search_domains", "이번 검색 결과의 출처 분포",
                           "많이 잡히고 정확한 출처를 ## 우선 출처 위쪽으로 올린다", dict(domains.most_common(8))))

    # --- what the user did on the replaced page
    fb = run.get("user_feedback") or {}
    if fb.get("ignored"):
        out.append(finding("user_ignored", f"사용자가 {len(fb['ignored'])}건을 무시했다",
                           "공통된 출처·제목 패턴이 있으면 ## 피할 출처·패턴에 근거와 함께 적는다", fb["ignored"]))
    if fb.get("bought"):
        out.append(finding("user_bought", f"사용자가 {len(fb['bought'])}건을 샀다",
                           "이런 딜을 더 찾도록 비슷한 검색어와 출처를 ## 검색어·## 우선 출처에 강화한다", fb["bought"]))

    # --- source health
    for e in run.get("errors", []):
        out.append(finding("source_error", f"{e['source']}: {e['error']}",
                           "검색 사이트가 막혔다면 ## 피할 출처·패턴에 적고 대체 출처를 찾는다"))

    return {"run": {k: run.get(k) for k in ("at", "found", "new", "notified", "by_source", "dropped")},
            "search_categories": search_cats, "findings": out}


def playbook_problems(text: str | None) -> list[str]:
    if text is None:
        return ["playbook: missing data/playbook.md"]
    out = []
    if len(text) > PLAYBOOK_LIMIT:
        out.append(f"playbook: {len(text)} chars exceeds {PLAYBOOK_LIMIT}")
    for sec in PLAYBOOK_SECTIONS:
        if sec not in text:
            out.append(f"playbook: section '{sec}' is missing")
    return out


def main() -> int:
    common.setup_io()
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    report = review(common.load_data("config", {}), common.load_data("runs", {"runs": []}), load_feed())
    path = common.DATA / PLAYBOOK
    report["playbook"] = {"chars": len(path.read_text(encoding="utf-8")) if path.exists() else None,
                          "limit": PLAYBOOK_LIMIT}
    common.dump(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
