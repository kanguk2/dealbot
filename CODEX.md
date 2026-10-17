# CODEX.md — 딜봇 실행 지침

이 저장소는 개인용 딜 알림 봇이다. Codex Automation은 실행될 때마다 이 문서를 읽고 아래 순서를 **한 번** 수행한다.
결정적인 일(수집 스크립트, 중복 판정, 필터, 알림, 검증)은 전부 `scripts/`가 한다. Codex가 판단할 일은 **2단계 웹 검색** 하나뿐이다.

## 파일 경계

| 경로 | Codex |
| --- | --- |
| `data/feed.json`, `data/seen.json`, `data/runs.json` | 스크립트를 통해 갱신하고 커밋한다. 손으로 고치지 않는다 |
| `data/config.json`, `data/notifiers.json` | 읽기만 한다. 사용자가 웹 UI에서 고친다 |
| `docs/`, `scripts/`, `schemas/`, 이 문서 | **수정 금지.** 버그를 발견하면 `--source-error`로 runs.json에 적고 넘어간다 |
| `.tmp/` | 작업용 임시 폴더. 커밋하지 않는다 (gitignore됨) |

## 실행 순서

### 1. 최신화하고 설정 읽기

```bash
git pull --rebase
mkdir -p .tmp
```

- `data/config.json`에서 `enabled: true`인 카테고리만 대상으로 한다.
- `data/runs.json`의 `runs[0].at`이 **기준 시각**이다. 그 이후에 올라온 것만 찾는다. 기록이 없으면 최근 48시간으로 한다.

### 2. 웹 검색 (판단이 필요한 유일한 단계)

`sources`에 `"search"`가 들어 있는 카테고리만 검색한다. 없으면 이 단계를 건너뛰고 `.tmp/search.json`에 `[]`를 쓴다.

- 검색어는 카테고리 `keywords`와 config `search_hints`를 조합한다. 카테고리당 3개 이하, 전체 8개 이하.
- 핫딜 커뮤니티와 공식 이벤트 페이지를 우선한다. 기준 시각 이후 글만 고른다.
- 카테고리 `exclude` 단어가 들어간 글은 고르지 않는다.
- 로그인, 캡차, 차단 우회를 시도하지 않는다. 403·429를 받으면 그 사이트는 이번 실행에서 포기한다.
- 결과가 0건이어도 정상이다. 억지로 채우지 않는다.

찾은 것을 `.tmp/search.json`에 아래 형식의 **배열**로 쓴다.

```json
[
  {
    "category": "points",
    "title": "[KB Pay] 10월 결제 이벤트 최대 1만 포인트",
    "url": "https://실제로-열어-본-페이지",
    "source": "search",
    "price_krw": null,
    "original_price_krw": null,
    "discount_pct": null,
    "starts": "2026-10-16",
    "ends": "2026-10-31",
    "summary": "한 줄 요약. 응모 조건이 있으면 여기에."
  }
]
```

규칙:

- **모르는 값은 `null`. 절대 지어내지 않는다.** 가격·할인율·기간은 페이지에 적혀 있을 때만 쓴다.
- `url`은 실제로 연 페이지 주소다. `category`는 config의 카테고리 `id`다.
- 가격은 원 단위 정수(`12900`), 날짜는 `YYYY-MM-DD`다.
- `id`, `key`, `found_at`, `notified`, `status`는 쓰지 않는다. 스크립트가 채운다.

검색 자체가 실패했으면(네트워크 차단 등) 사유를 기억해 두었다가 3단계에서 `--source-error`로 넘긴다.

### 3. 수집·중복 제거·필터·기록

```bash
python scripts/run_deterministic.py --extra .tmp/search.json
# 검색이 실패했으면:
python scripts/run_deterministic.py --extra .tmp/search.json --source-error "search=사유 한 줄"
```

이 스크립트가 하는 일:
- `scripts/sources/`의 결정적 소스(RSS, 에픽)를 실행한다. 소스 하나가 실패해도 나머지는 진행하고, 실패는 runs.json `errors`에 남긴다.
- 후보를 `seen.json`과 대조해 새 항목만 남기고 `key`와 `id`를 붙인다.
- `exclude`, RSS 키워드 매칭, `min_discount_pct`, `max_price_krw`, 마감일로 거른다.
- `feed.json` 앞에 추가하고(`feed_limit`까지), `seen.json`에 키를 넣고, `runs.json`에 실행을 기록한다.

### 4. 검증

```bash
python scripts/validate.py --record
```

실패하면(종료 코드 1) **알림을 보내지 않는다.**

```bash
git checkout -- data/feed.json data/seen.json
git add data/runs.json
git commit -m "codex: run <YYYY-MM-DD HH:MM> (validate failed)"
git push
```

그리고 6단계 보고로 넘어간다.

### 5. 알림

```bash
python scripts/notify.py --since-run
```

우선순위(`instant`, `daily`, `weekly`), 조용한 시간, 채널별 규칙은 스크립트가 처리한다. 전송 결과는 feed 항목의 `notified`와 runs.json에 기록된다. 채널 하나가 실패해도 다른 채널에는 영향이 없다.

### 6. 커밋·푸시·보고

```bash
git add data/
git commit -m "codex: run <YYYY-MM-DD HH:MM> (+<새 항목 수> new)"
git push
```

- 시각은 `runs.json`의 `runs[0].at`(KST)을 쓰고, 새 항목 수는 `runs[0].new`를 쓴다. 예: `codex: run 2026-10-17 09:03 (+3 new)`
- `data/` 밖의 변경은 커밋하지 않는다. `git status`로 확인한다.
- 새 항목이 0건이어도 runs.json이 바뀌므로 커밋한다.
- push가 거절되면 `git pull --rebase` 후 다시 push한다. 리베이스 충돌이 나면 사용자가 UI에서 동시에 수정한 것이다. 이때는 `git rebase --abort && git reset --hard origin/main` 후 3단계부터 한 번만 다시 수행한다.

마지막에 한 줄로 보고한다.

```
찾은 N건, 새 M건, 알림 K건, 오류: [소스: 사유, ...] 또는 없음
```

N은 `runs[0].found`, M은 `runs[0].new`, K는 `runs[0].notified`, 오류는 `runs[0].errors`에서 가져온다.

## health 체크 (주 1회 별도 Automation)

`data/runs.json`의 `runs[0].at`을 확인한다.

- 36시간 이내면 아무것도 하지 않고 "정상"이라고만 보고한다.
- 36시간을 넘겼으면 `python scripts/notify.py --health-alert`를 실행하고, 최근 `errors`로 짐작되는 원인을 한 줄로 보고한다. 파일은 수정하지 않고 커밋하지 않는다.

## 금지

- `docs/`, `scripts/`, `schemas/`, `CODEX.md` 수정
- `data/*.json`을 스크립트를 거치지 않고 직접 편집 (유일한 예외는 4단계의 `git checkout`)
- 로그인, 캡차, 프록시, 차단 우회
- 토큰이나 웹훅 주소를 저장소 파일에 쓰기 (시크릿은 환경변수에만 있다)
