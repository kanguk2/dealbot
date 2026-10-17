# CODEX.md — 딜봇 실행 지침

이 저장소는 개인용 딜 알림 봇이다. Codex는 실행될 때마다 이 문서를 읽고 아래 순서를 **한 번** 수행한다.

> **정기 실행 방식**: 매일 09:00 PC의 Codex 앱 예약 작업(ChatGPT 구독)이 `.github/codex/scheduled.md`를 따른다. 1·3·4·7단계는 `scripts/local_run.py`(prepare/collect/publish)가 하고, Codex는 2단계 검색과 6단계 플레이북 개선만 한다. 5단계 알림은 push 후 GitHub Actions `notify.yml`이 보낸다. API 키가 있으면 `dealbot.yml`이 Actions 안에서 같은 일을 한다(`.github/codex/search.md`, `review.md`). 사람이 Codex에서 직접 돌릴 때는 아래 전체 순서를 따른다.
결정적인 일(수집 스크립트, 중복 판정, 필터, 알림, 검증, 회고 점검)은 전부 `scripts/`가 한다. Codex가 판단할 일은 두 가지다. **2단계 웹 검색**과 **7단계 플레이북 개선**이다.

매 실행마다 피드 페이지는 **그 실행에서 새로 잡힌 딜로 통째로 바뀐다**(이전 결과는 화면에서 사라진다). 아직 보내지 않은 묶음 알림은 `feed.json`의 `pending`에 따로 남아 있으니 신경 쓰지 않아도 된다.

## 파일 경계

| 경로 | Codex |
| --- | --- |
| `data/feed.json`, `data/seen.json`, `data/runs.json` | 스크립트를 통해 갱신하고 커밋한다. 손으로 고치지 않는다 |
| `data/playbook.md` | 검색 요령. 2단계에서 읽고 6단계에서 **직접 고친다** (아래 규칙대로) |
| `data/interests.json`, `data/links.json` | 읽기만 한다. 관심사는 사용자가 웹 UI에서 저장하고, 모아보기 링크는 개발 쪽에서 관리한다 |
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

### 2. 웹 검색 (판단이 필요한 단계 ①)

`sources`에 `"search"`가 들어 있는 카테고리만 검색한다. 없으면 이 단계를 건너뛰고 `.tmp/search.json`에 `[]`를 쓴다.

**먼저 `data/playbook.md`와 `data/interests.json`을 읽는다.** 플레이북에는 지난 실행들에서 배운 검색어, 우선 출처, 피할 출처, 판단 기준이 들어 있다. 이 문서를 따른다. `interests.json`의 `terms`(관심 키워드)와 `saved`(사용자가 ☆ 관심을 누른 딜)는 사용자가 특히 원하는 것이다. 검색어를 고를 때 이것과 겹치는 쪽을 먼저 쓴다(카테고리 범위 안에서).

- 검색어는 플레이북 `## 검색어`를 먼저 쓰고, 카테고리 `keywords`와 config `search_hints`로 보충한다. 카테고리당 3개 이하, 전체 8개 이하.
- 플레이북 `## 우선 출처`를 먼저 보고, `## 피할 출처·패턴`에 있는 것은 고르지 않는다. 기준 시각 이후 글만 고른다.
- **기한을 확인한다.** 이미 끝난 이벤트, 그리고 마감일이 오늘부터 config `min_days_left`일 이내인 이벤트는 고르지 않는다. 날짜 기준은 실행 시각(KST)이다. 마감일을 모르면 `ends: null`로 두면 스크립트가 처리한다.
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
- `exclude`, RSS 키워드 매칭, `min_discount_pct`, `max_price_krw`, 마감일(이미 끝남, `min_days_left` 이내)로 거른다.
- `feed.json`의 `items`를 이번 결과로 바꾸고(`feed_limit`까지), 알림 대기열 `pending`에 넣고, `seen.json`에 키를 넣고, `runs.json`에 실행을 기록한다. 걸러진 이유(`dropped`, `drop_samples`)와 사용자가 이전 페이지에서 누른 무시·샀음(`user_feedback`)도 함께 기록한다.

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

그리고 7단계 보고로 넘어간다(5·6단계는 건너뛴다).

### 5. 알림

```bash
python scripts/notify.py --since-run
```

우선순위(`instant`, `daily`, `weekly`), 조용한 시간, 채널별 규칙은 스크립트가 처리한다. 전송 결과는 feed 항목의 `notified`와 runs.json에 기록된다. 채널 하나가 실패해도 다른 채널에는 영향이 없다.

### 6. 회고: 플레이북 개선 (판단이 필요한 단계 ②)

다음 실행이 더 잘 찾도록 이번 실행을 돌아보고 `data/playbook.md`를 고친다.

```bash
python scripts/review_run.py > .tmp/review.json
```

`.tmp/review.json`의 `findings`를 하나씩 본다. 각 항목에 `hint`가 있다. 고치는 규칙은 다음과 같다.

- **근거가 있는 것만 고친다.** review의 finding이나 2단계에서 직접 겪은 일(막힌 사이트, 기한이 없던 페이지, 엉뚱한 결과)만 근거가 된다. 추측으로 고치지 않는다.
- 한 번에 **최대 3군데**만 고친다. 고칠 근거가 없으면 고치지 않는다. 그것도 정상이다.
- 검색어 결과가 계속 0건이면 바꾼다. 잘 잡히는 검색어는 위로 올린다.
- 사용자가 **무시**한 딜(`user_ignored`)에 공통 패턴(출처, 제목 단어)이 있으면 `## 피할 출처·패턴`에 근거와 함께 적는다. 사용자가 **샀음**을 누른 딜(`user_bought`)은 비슷한 것을 더 찾도록 `## 검색어`와 `## 우선 출처`에 반영한다.
- 관심사에 맞는 새 딜이 없으면(`interest_miss`) 관심 키워드가 들어간 검색어를 `## 검색어`에 하나 추가한다. 잘 맞았으면(`interest_hits`) 그 검색어와 출처를 유지한다.
- 기한이 지난 것(`dropped_ended`, `dropped_too_close`)이나 기한 없는 결과(`missing_ends`)가 나왔으면 `## 판단 기준`의 "학습한 규칙"에 구체적인 확인 방법을 적는다.
- 섹션 제목은 바꾸지 않는다. "고정 규칙"은 지우지 않는다. 12,000자를 넘기지 않는다. `## 최근 교훈`은 10줄 이하, `## 변경 이력`은 최근 20줄만 남긴다.
- 고칠 때마다 `## 변경 이력`에 한 줄을 추가한다. 형식은 `YYYY-MM-DD HH:MM · 무엇을 바꿨나 · 근거(finding type)`이다.

고친 뒤 `python scripts/validate.py`를 다시 돌린다. 실패하면 `git checkout -- data/playbook.md`로 플레이북 변경만 되돌린다.

### 7. 커밋·푸시·보고

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
- `data/*.json`을 스크립트를 거치지 않고 직접 편집 (예외: 4단계의 `git checkout`). `data/playbook.md`는 6단계 규칙대로 직접 고친다
- 로그인, 캡차, 프록시, 차단 우회
- 토큰이나 웹훅 주소를 저장소 파일에 쓰기 (시크릿은 환경변수에만 있다)
