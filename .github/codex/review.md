이 저장소는 개인용 딜 알림 봇이다. 너는 자동 실행(PC의 `scripts/codex_tick.py` 또는 GitHub Actions) 안에서 **회고 단계 하나만** 맡는다. 이번 실행의 수집·알림은 이미 끝났다.

1. `CODEX.md`의 "6. 회고: 플레이북 개선"을 읽는다.
2. `.tmp/review.json`(이번 실행 점검 결과), `data/playbook.md`, `data/interests.json`, `.tmp/search-report.txt`(있으면, 이번 검색 단계 보고)를 읽는다.
3. 6단계 규칙대로 근거가 있는 것만, 최대 3군데 `data/playbook.md`를 고친다. 고칠 근거가 없으면 고치지 않는다. 고칠 때마다 `## 변경 이력`에 한 줄을 남긴다.
4. `data/playbook.md` 말고는 어떤 파일도 고치지 않는다(다른 변경은 버려진다). 스크립트를 실행하지 않는다.
5. 마지막에 한 줄로 보고한다: `플레이북 변경 N곳: … (근거 finding)` 또는 `변경 없음`.
