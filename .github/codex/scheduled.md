이 저장소는 개인용 딜 알림 봇이다. 이 작업은 Codex 앱의 예약 작업(ChatGPT 구독)으로 매일 한 번 돈다. 판단이 필요한 두 가지(웹 검색, 플레이북 개선)만 네가 하고, 나머지는 `scripts/local_run.py`가 한다. 자세한 규칙은 `CODEX.md`에 있다.

1. `py -3 scripts/local_run.py prepare`
   - 최신 main을 받고 의존성을 설치한다. Windows에서 `py`가 없으면 `python`을 쓴다.
2. 웹 검색 (CODEX.md 2단계)
   - `data/config.json`, `data/playbook.md`, `data/interests.json`, `data/runs.json`을 읽는다. 기준 시각은 `runs[0].at`이다.
   - 플레이북의 검색어와 관심 키워드부터 웹 검색한다.
   - 결과는 `.tmp/search.json`에 JSON 배열로 쓴다. 0건이면 `[]`를 쓴다. 형식은 CODEX.md 2단계와 같다.
   - 모르는 값은 null로 두고 지어내지 않는다. 이미 끝났거나 마감이 config `min_days_left`일 이내인 이벤트는 넣지 않는다.
   - 로그인, 캡차, 차단 우회는 시도하지 않는다.
3. `py -3 scripts/local_run.py collect`
   - 검색 자체를 못 했으면 `--search-error "사유"`를 붙인다.
4. 회고 (CODEX.md 6단계)
   - `.tmp/review.json`의 findings를 근거로 `data/playbook.md`를 고친다. 근거가 있을 때만, 최대 3곳까지다.
   - 고칠 때마다 `## 변경 이력`에 한 줄을 남긴다. 근거가 없으면 고치지 않는다.
5. `py -3 scripts/local_run.py publish`
   - `data/`만 `codex: run …`으로 커밋해 main에 push한다. 알림은 push를 받은 GitHub Actions가 보낸다.

금지:
- `data/playbook.md`와 `.tmp/search.json` 말고는 어떤 파일도 직접 고치지 않는다. publish는 `data/` 밖에 변경이 있으면 거부한다.
- force push, 히스토리 수정은 하지 않는다.

마지막에 publish가 출력한 한 줄(`published: 찾은 N건, 새 M건, 오류: …`)과 플레이북 변경 수를 보고한다.
