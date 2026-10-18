이 저장소는 개인용 딜 알림 봇이다. 너는 자동 실행(PC의 `scripts/codex_tick.py` 또는 GitHub Actions) 안에서 **웹 검색 단계 하나만** 맡는다. 나머지 단계(수집 스크립트, 중복 제거, 알림, 커밋)는 스크립트가 한다.

1. `CODEX.md`의 "파일 경계", "1. 최신화하고 설정 읽기", "2. 웹 검색"을 읽는다. 1단계의 `git pull`은 하지 않는다(이미 최신이다).
2. `data/config.json`, `data/playbook.md`, `data/interests.json`, `data/runs.json`을 읽는다. **지금 진행 중이고 마감 전인 이벤트**를 찾는다(올라온 날짜로 거르지 않는다. 이미 잡은 건 스크립트가 거른다). 오늘 날짜는 셸 명령(`date` 또는 PowerShell `Get-Date`)으로 확인한다(KST = UTC+9).
3. 카테고리마다(`sources`에 `search`가 있는 것 전부) 최소 1개 이상 검색어를 써서 웹 검색을 하고, 각 후보의 `category`를 그 카테고리 id로 정한 뒤, 결과를 `.tmp/search.json`에 **JSON 배열**로 쓴다. 0건이면 `[]`를 쓴다.
   - 모르는 값은 null. 지어내지 않는다. url은 실제로 확인한 페이지다.
   - 이미 끝났거나 마감이 config `min_days_left`일 이내인 이벤트는 넣지 않는다.
4. `.tmp/search.json` 말고는 어떤 파일도 만들거나 고치지 않는다. 스크립트도 실행하지 않는다(쓰기 결과는 버려진다).
5. 마지막에 한 줄로 보고한다: `검색어 N개, 후보 M건, 막힌 사이트: …`
