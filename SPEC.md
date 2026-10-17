# 딜봇(DealBot) 구현 스펙 — Claude 구현 · Codex 주기 실행

Oct 17, 2026 · @강욱

## 1. 프로젝트 개요

**한 줄 요약**: 내가 정한 분야·키워드의 특가, 포인트 적립, 할인 이벤트를 정해진 주기로 수집해서, 내가 고른 채널(Slack·Discord·Telegram·폰 푸시·카카오톡·이메일)로 알려주는 개인용 봇. 설정과 피드는 GitHub Pages 정적 페이지에서 보고 편집한다.

**역할 분담**

| 역할 | 담당 | 산출물 |
| --- | --- | --- |
| 저장소·UI·알림 코드 구현 | Claude (이 대화) | 정적 페이지, JSON 스키마, 알림 스크립트, 설정 파일, README |
| 주기적 수집·판단·알림 실행 | Codex Automation (클라우드) | 저장소를 열어 config를 읽고, 딜을 찾아 feed.json을 갱신·커밋하고, 알림 스크립트를 호출 |
| 설정·키워드·주기 관리 | 사용자 | github.io 페이지에서 편집, Codex Automation 주기 설정 |

Codex는 코드를 거의 짜지 않는다. Claude가 만들어 둔 스크립트와 데이터 규약을 **사용하는 쪽**이다. 그래서 Codex 프롬프트는 짧고, 수집 로직이 바뀌어도 코드가 아니라 프롬프트나 config만 고치면 된다.

**목표**

- 서버를 직접 운영하지 않는다. 코드·설정·데이터는 전부 GitHub 저장소 하나에 둔다.
- 설정(분야, 키워드, 주기, 알림 채널)은 코드 수정 없이 웹 UI에서 바꾼다.
- 알림 채널은 플러그인 구조로 두어, 채널 추가가 파일 하나로 끝나게 한다.
- 수집 소스는 크롤링 의존을 최소화한다. 공식 API, RSS, 집계 채널, 이메일 우선.

**비목표 (이번 범위 밖)**

- 로그인이 필요한 개인 포인트 잔액·카드 실적 조회
- 캡차 우회, 프록시, 차단 회피
- 다중 사용자 지원. 사용자는 1명이다.
- 실시간(분 단위) 알림. 하루 2\~6회 실행이면 충분하다.

**사용자**: 펌웨어 개발자 1명. Python·Linux·Git은 익숙하고, 웹 프론트엔드는 깊지 않다. UI는 단순할수록 좋다.

## 2. 전체 아키텍처

&#91;embedded content: 아키텍처 · 4개 구성요소, 저장소가 중심\]

저장소가 유일한 상태 저장소다. UI는 저장소의 JSON을 읽고 쓰고, Codex는 저장소를 클론해 같은 JSON을 읽고 갱신한 뒤 Claude가 만든 알림 스크립트를 실행한다. 서버는 없다.

**설계 원칙**

- 데이터 규약(JSON 스키마)이 계약이다. UI·Codex·알림 스크립트는 서로를 모르고 파일만 본다.
- 결정적인 일(중복 판정, 알림 전송, 스키마 검증)은 스크립트로 고정한다. Codex는 그 스크립트를 호출만 한다. LLM의 변동성이 들어갈 자리를 "무엇을 찾을지" 하나로 좁힌다.
- Codex가 커밋하는 파일은 `data/` 아래로 제한한다. UI 코드나 스크립트는 Codex가 건드리지 않는다.

## 3. 저장소 구조 (Claude가 만든다)

```markdown
dealbot/
├── docs/                    # GitHub Pages 소스 (Settings → Pages → /docs)
│   ├── index.html           # 피드 화면 (기본 페이지)
│   ├── settings.html        # 설정 화면
│   ├── app.js               # JSON 읽기, 폼 바인딩, GitHub API 커밋
│   └── style.css
├── data/                    # Codex와 UI가 읽고 쓰는 상태. 이 폴더만 Codex가 커밋
│   ├── config.json          # 분야·키워드·조건·주기
│   ├── notifiers.json       # 알림 채널 설정 (토큰은 없음)
│   ├── feed.json            # 잡힌 딜 목록 (최근 500건 유지)
│   ├── seen.json            # 중복 판정 키 목록 (30일 보관)
│   └── runs.json            # 실행 로그 (최근 50회)
├── scripts/
│   ├── notify.py            # feed의 새 항목을 채널로 전송
│   ├── dedupe.py            # 후보 → seen 대조 → 새 항목만 출력
│   ├── validate.py          # JSON 스키마 검증, 커밋 전 실행
│   ├── sources/             # 결정적으로 받을 수 있는 소스 어댑터
│   │   ├── epic_free.py     # 에픽게임즈 무료 게임 API
│   │   ├── rss.py           # 범용 RSS 리더 (config의 URL 목록)
│   │   └── __init__.py
│   └── notifiers/           # 채널별 플러그인, 파일 하나 = 채널 하나
│       ├── base.py
│       ├── slack.py
│       ├── discord.py
│       ├── telegram.py
│       ├── ntfy.py
│       ├── pushover.py
│       ├── kakao.py
│       └── email.py
├── schemas/                 # JSON Schema. UI 검증과 validate.py가 공용
│   ├── config.schema.json
│   ├── feed.schema.json
│   └── notifiers.schema.json
├── CODEX.md                 # Codex Automation이 매 실행마다 읽는 운영 지침
├── requirements.txt
└── README.md                # 설치·토큰 발급·Pages 설정 순서
```

**브랜치**: `main` 하나. Pages는 `main`의 `/docs`에서 서빙. Codex가 `data/`만 커밋하므로 충돌이 날 일이 거의 없다.

**시크릿**: 토큰은 저장소에 두지 않는다. Codex 클라우드 환경의 시크릿(환경변수)에 넣고 `notify.py`가 환경변수로 읽는다. 변수 이름은 7절 표에 고정한다.

## 4. 데이터 스키마

네 파일이 세 참여자(UI, Codex, 스크립트) 사이의 계약이다. 필드를 바꾸면 `schemas/`와 이 절을 같이 고친다.

**config.json** — 무엇을 찾을지

```json
{
  "version": 1,
  "schedule": { "times": ["09:00", "13:00", "19:00"], "timezone": "Asia/Seoul" },
  "categories": [
    {
      "id": "games", "name": "게임", "enabled": true,
      "keywords": ["무료", "에픽", "스팀 세일"], "exclude": ["모바일"],
      "sources": ["epic_free", "rss:ruliweb_hotdeal", "search"],
      "min_discount_pct": 50, "max_price_krw": null,
      "priority": "instant"
    },
    {
      "id": "points", "name": "포인트·적립", "enabled": true,
      "keywords": ["출석", "캐시백", "포인트 소멸", "적립 이벤트"], "exclude": [],
      "sources": ["search", "rss:ppomppu_event"],
      "priority": "daily"
    }
  ],
  "rss_feeds": { "ruliweb_hotdeal": "https://...", "ppomppu_event": "https://..." },
  "search_hints": ["뽐뿌 핫딜", "알구몬", "카드사 이벤트"],
  "quiet_hours": { "start": "23:00", "end": "08:00" },
  "feed_limit": 500, "seen_ttl_days": 30
}
```

`schedule.times`는 UI 표시용이자 Codex 프롬프트에 넣을 값이다. 실제 실행 주기는 Codex Automation 설정이 결정하므로, UI에서 바꾸면 "Codex Automation 주기도 바꾸세요" 안내를 띄운다. `priority`는 `instant`(즉시 전송) | `daily`(하루 1회 묶음) | `weekly`.

**feed.json** — 찾은 것 (Codex가 추가, 최신순)

```json
{
  "items": [
    {
      "id": "a1b2c3",              "key": "에픽 무료|ghostrunner|0",
      "category": "games",         "title": "에픽게임즈 이번 주 무료: Ghostrunner",
      "url": "https://...",         "source": "epic_free",
      "price_krw": 0,              "original_price_krw": 32000, "discount_pct": 100,
      "starts": "2026-10-16",      "ends": "2026-10-23",
      "found_at": "2026-10-17T09:03:00+09:00",
      "summary": "한 줄 요약. 조건이 있으면 여기에.",
      "notified": ["slack", "ntfy"], "status": "new"
    }
  ]
}
```

`key`는 `dedupe.py`가 만든다: 제목 정규화(소문자, 공백·특수문자 제거) + 가격. URL만으로 비교하지 않는다. `status`는 `new` | `seen` | `bought` | `ignored`, UI에서 사용자가 바꾼다.

**seen.json** — 중복 판정용

```json
{ "keys": { "에픽 무료|ghostrunner|0": "2026-10-17" } }
```

`seen_ttl_days`가 지난 키는 `dedupe.py`가 지운다.

**notifiers.json** — 어디로 보낼지 (토큰 없음, 토큰은 환경변수)

```json
{
  "channels": [
    { "id": "slack",    "type": "slack",    "enabled": true,  "target": "#dealbot", "priorities": ["instant", "daily"] },
    { "id": "ntfy",     "type": "ntfy",     "enabled": true,  "target": "my-dealbot-topic", "priorities": ["instant"] },
    { "id": "telegram", "type": "telegram", "enabled": false, "target": "", "priorities": ["instant", "daily", "weekly"] },
    { "id": "kakao",    "type": "kakao",    "enabled": false, "target": "me",  "priorities": ["daily"] },
    { "id": "email",    "type": "email",    "enabled": false, "target": "me@example.com", "priorities": ["weekly"] }
  ],
  "format": { "group_by_category": true, "max_items_per_message": 10, "include_summary": true }
}
```

**runs.json** — 실행 로그

```json
{ "runs": [ { "at": "2026-10-17T09:03:00+09:00", "found": 12, "new": 3, "notified": 3, "errors": [], "by_source": { "epic_free": 2, "search": 10 } } ] }
```

## 5. 정적 UI 요구사항 (Claude가 만든다)

프레임워크 없이 HTML + 바닐라 JS 파일 두 장. 폰 브라우저에서 편집 가능해야 한다.

**피드 화면 `index.html`**

- `data/feed.json`을 fetch해 최신순 카드 목록. 카테고리 탭, 상태 필터(new / bought / ignored).
- 카드: 제목(링크), 가격·할인율, 마감일, 소스, 요약, 상태 버튼(샀음 / 무시).
- 상태 버튼은 feed.json의 `status`를 바꿔 커밋한다.
- 상단에 마지막 실행 시각과 결과(runs.json 최신 1건). 24시간 이상 실행이 없으면 경고 배너.
- 월간 통계 한 줄: 이번 달 잡힌 건수, `bought` 건수, `original_price_krw − price_krw` 합계(아낀 금액 추정).

**설정 화면 `settings.html`**

- 카테고리 목록: 추가·삭제·켜기/끄기, 이름, 키워드(태그 입력), 제외어, 소스 체크박스, 최소 할인율, 최대 가격, 우선순위.
- 실행 시간 목록, 조용한 시간대.
- 알림 채널 목록: 켜기/끄기, 대상(채널명·토픽·chat\_id), 받을 우선순위. 토큰 입력란은 없다. 대신 "토큰은 Codex 시크릿 `DEALBOT_SLACK_WEBHOOK`에 넣으세요" 안내.
- 저장 버튼 → `schemas/`로 검증 → GitHub Contents API로 `data/config.json`, `data/notifiers.json` 커밋.
- 저장 후 "실행 시간을 바꿨으면 Codex Automation 주기도 바꾸세요" 안내.

**GitHub API 연동**

- Fine-grained PAT(이 저장소, Contents: Read and write만)를 첫 방문 때 입력받아 `localStorage`에 저장. 설정 화면에 "토큰 지우기" 버튼.
- 커밋 흐름: GET 파일(sha 획득) → 로컬 수정 → PUT(sha 포함). 409면 다시 GET 후 재시도 1회, 실패하면 사용자에게 알림.
- 커밋 메시지: `ui: update config` / `ui: mark <id> bought`.
- 저장소는 비공개여도 된다. Pages는 비공개 저장소에서도 동작한다(Pro 이상). 공개 저장소라면 feed·config에 민감 정보가 없는지 README에 명시.

**완료 기준**

- [ ] 폰 Safari·Chrome에서 설정 저장이 된다
- [ ] 잘못된 JSON(키워드 비움 등)은 저장 전에 막힌다
- [ ] feed 500건에서도 첫 화면이 1초 안에 뜬다

## 6. 실행 흐름 (Codex가 매 실행마다 따르는 순서)

Codex는 `CODEX.md`를 읽고 아래 순서를 그대로 수행한다. 판단이 필요한 건 2단계뿐이고 나머지는 스크립트 호출이다.

1. `git pull` 후 `data/config.json`, `data/notifiers.json` 읽기. `enabled: true`인 카테고리만 대상.
2. 카테고리별 후보 수집. 세 경로를 섞는다.
   - 결정적 소스: `python scripts/sources/epic_free.py`, `python scripts/sources/rss.py <feed_id>` → JSON 후보 출력
   - 검색: config의 `keywords`와 `search_hints`를 조합해 웹 검색. 핫딜 커뮤니티·공식 이벤트 페이지 우선. 지난 실행 이후(`runs.json` 마지막 `at`) 올라온 것만.
   - 각 후보를 feed 항목 형식으로 정리: 제목, URL, 가격, 할인율, 기간, 한 줄 요약. 모르는 값은 `null`, 지어내지 않는다.
3. `python scripts/dedupe.py candidates.json` → `seen.json`과 대조해 새 항목만 반환, `key` 부여, 만료 키 정리.
4. 필터 적용: `exclude` 포함 → 제외, `min_discount_pct` 미만 → 제외, `max_price_krw` 초과 → 제외, 마감 지난 것 → 제외.
5. `feed.json` 앞에 추가(최대 `feed_limit`), `seen.json`에 키 추가, `runs.json`에 기록.
6. `python scripts/validate.py` → 실패하면 커밋하지 않고 오류를 `runs.json`에만 남긴다.
7. `python scripts/notify.py --since-run` → 이번 실행의 새 항목을 우선순위·채널 규칙대로 전송. 전송 결과를 feed 항목 `notified`에 기록.
8. `data/` 커밋·푸시. 메시지 `codex: run 2026-10-17 09:03 (+3 new)`.

**우선순위 처리**

- `instant`: 그 실행에서 바로 전송. 단 `quiet_hours` 안이면 다음 실행으로 미룬다.
- `daily`: 하루 첫 실행(`schedule.times[0]`)에서 전날 누적분을 한 메시지로 묶어 전송.
- `weekly`: 월요일 첫 실행에서 지난 주 누적분.

**실패 처리**

- 소스 하나가 실패해도 나머지는 진행. 실패는 `runs.json.errors`에 소스명과 사유.
- 연속 3회 같은 소스 실패 → `notify.py`가 "소스 X 3회 연속 실패" 알림 1건 전송(하루 1회 제한).
- 검색에서 0건이면 정상. 억지로 채우지 않는다.

**금지**

- `docs/`, `scripts/`, `schemas/` 수정 금지. 버그를 발견하면 `runs.json.errors`에 적고 넘어간다.
- 로그인, 캡차, 차단 우회 시도 금지. 403·429를 받으면 그 소스는 이번 실행에서 포기.

## 7. 알림 레이어 (Claude가 만든다)

채널 하나 = `scripts/notifiers/` 파일 하나. `base.py`의 `Notifier.send(items, priority) -> SendResult` 인터페이스만 지키면 `notify.py`가 자동으로 집어 쓴다. 토큰은 전부 환경변수.

| 채널 | 방식 | 필요한 환경변수 | notifiers.json `target` | 비고 |
| --- | --- | --- | --- | --- |
| Slack | Incoming Webhook POST | `DEALBOT_SLACK_WEBHOOK` | 표시용 채널명 | 가장 쉬움. Block Kit로 카드 형식 |
| Discord | Webhook POST | `DEALBOT_DISCORD_WEBHOOK` | 표시용 채널명 | Embed 형식 |
| Telegram | Bot API `sendMessage` | `DEALBOT_TELEGRAM_TOKEN`, `DEALBOT_TELEGRAM_CHAT_ID` | chat\_id | MarkdownV2, 링크 미리보기 끔 |
| ntfy (폰 푸시) | `POST https://ntfy.sh/<topic>` | `DEALBOT_NTFY_TOKEN`(선택) | 토픽명 | 앱 설치만 하면 끝. 토픽명을 길고 추측 불가하게 |
| Pushover (폰 푸시) | API POST | `DEALBOT_PUSHOVER_TOKEN`, `DEALBOT_PUSHOVER_USER` | — | 앱 1회 구매. 알림음·우선순위 세밀 제어 |
| 카카오톡 나에게 보내기 | REST API `memo/default/send` | `DEALBOT_KAKAO_REST_KEY`, `DEALBOT_KAKAO_REFRESH_TOKEN` | `me` | refresh\_token으로 access\_token 매번 재발급. 링크는 등록 도메인만 허용 |
| 이메일 | SMTP | `DEALBOT_SMTP_HOST`, `DEALBOT_SMTP_USER`, `DEALBOT_SMTP_PASS` | 받을 주소 | Gmail은 앱 비밀번호. weekly 묶음용 |

**폰 알림 추천**: ntfy가 설정 5분, 무료, 토큰 불필요라 첫 채널로 적합하다. 더 세밀한 제어가 필요하면 Pushover.

**카카오톡 주의**: 공식 경로가 "나에게 보내기" 하나뿐이고, 카카오 개발자 콘솔에서 앱 등록 → 동의 → 토큰 발급 과정이 필요하다. README에 발급 순서를 적어 두고, 토큰 만료(refresh\_token 약 2개월) 시 `notify.py`가 "카카오 토큰 갱신 필요" 알림을 다른 채널로 보낸다.

**메시지 형식 (공통)**

```markdown
[게임] 새 딜 3건 · 10/17 09:03
• Ghostrunner 무료 (정가 32,000원) · 에픽 · ~10/23
  https://...
• ...
피드 보기: https://<user>.github.io/dealbot/
```

- 채널별 서식(Block Kit, Embed, MarkdownV2)은 플러그인 안에서 변환. 공통 입력은 feed 항목 배열.
- `max_items_per_message` 초과 시 나눠 보내되, 상한 3개 메시지. 넘치면 "외 N건, 피드에서 확인".
- 전송 실패는 재시도 1회 후 `runs.json.errors`. 다른 채널에는 영향 없음.

**로컬 테스트**: `python scripts/notify.py --dry-run --sample` → 샘플 항목으로 각 채널 포맷을 stdout에 출력. `--channel slack` 으로 실제 전송 1건 테스트.

## 8. Codex Automation 설정

Codex는 [클라우드에서 예약·반복 작업(Automation)](https://openai.com/academy/codex-automations)을 지원한다. 로컬 Codex는 노트북이 깨어 있어야 하므로 반드시 **클라우드 환경**에 등록한다.

**클라우드 환경 준비**

1. Codex 웹에서 `dealbot` 저장소를 환경으로 추가.
2. 셋업 스크립트: `pip install -r requirements.txt`.
3. 인터넷 접근 켜기. 도메인 허용 목록에 넣을 것: `github.com`, `api.github.com`, 알림 API(`hooks.slack.com`, `discord.com`, `api.telegram.org`, `ntfy.sh`, `api.pushover.net`, `kapi.kakao.com`, `kauth.kakao.com`), 소스 도메인(에픽 API, RSS 호스트, 핫딜 커뮤니티). 검색을 쓰려면 검색 결과가 열리는 도메인도 필요하므로, 허용 목록이 좁으면 검색 경로는 실질적으로 막힌다. 처음엔 결정적 소스 + RSS 위주로 가고, 검색은 허용 목록을 넓힌 뒤 켠다.
4. 시크릿(환경변수)에 7절 표의 변수 등록. 쓰는 채널 것만.
5. 저장소 쓰기 권한: Codex GitHub 앱이 `main`에 푸시할 수 있어야 한다. 브랜치 보호를 걸었다면 `data/` 경로 예외 또는 Codex 봇 계정 예외.

**Automation 등록**

- 환경: 위에서 만든 `dealbot`
- 주기: `config.json`의 `schedule.times`와 맞춘다. 처음엔 하루 2회(09:00, 19:00 KST). 사용량을 보고 늘린다.
- 프롬프트: 11절의 것을 그대로. 길게 쓰지 않는다. 세부 규칙은 저장소의 `CODEX.md`가 들고 있으므로 프롬프트는 "CODEX.md대로 한 번 실행하고 커밋해"에 가깝다.
- 결과 확인: Automation 실행 기록에서 커밋 여부와 `runs.json` 요약을 본다.

**비용 감각**: 실행 1회 = Codex 세션 1회. 하루 2\~4회가 현실적이다. 1시간 간격은 사용량을 빠르게 소모한다.

**대안(백업)**: Codex 사용량이 부족하거나 클라우드 환경에서 국내 사이트가 막히면, 같은 저장소에 GitHub Actions 워크플로를 하나 추가해 결정적 소스(에픽·RSS)만 돌릴 수 있다. 스크립트가 이미 CLI라 `python scripts/run_deterministic.py && python scripts/notify.py` 두 줄이면 된다. 이 워크플로 파일은 Claude가 미리 만들어 두되 기본은 꺼 둔다(`workflow_dispatch`만).

## 9. 보안·운영

- **토큰은 두 곳에만**: 알림·소스 토큰은 Codex 시크릿, UI용 GitHub PAT는 내 폰 브라우저 localStorage. 저장소에는 토큰이 한 글자도 없어야 한다. `validate.py`가 `data/`에서 `token`, `webhook`, `hooks.slack.com` 같은 문자열을 발견하면 커밋을 막는다.
- **PAT 범위**: Fine-grained, 이 저장소만, Contents 읽기/쓰기만. 만료 90일로 두고 갱신.
- **커밋 경계**: Codex는 `data/`만, UI는 `data/config.json`·`data/notifiers.json`·`data/feed.json`의 `status`만 건드린다. 동시 수정 충돌은 UI 쪽이 재시도한다.
- **요청 예절**: 소스당 실행당 1회 요청. User-Agent에 `dealbot/1.0 (personal)` 명시. 403·429는 즉시 포기.
- **죽은 봇 감지**: UI 배너(24시간 미실행)와 별도로, `notify.py`가 "마지막 실행 36시간 경과" 알림을 보낼 수는 없다(실행이 안 되니까). 그래서 **주 1회 Codex Automation이 `runs.json` 최신 시각을 확인하고 정상이면 조용히, 아니면 알림**하는 health 프롬프트를 하나 더 둔다.
- **데이터 크기**: feed 500건, seen 30일, runs 50회로 잘라 저장소가 커지지 않게 한다.
- **되돌리기**: 전부 git이므로 잘못된 실행은 `data/` 커밋 하나 revert로 끝.

## 10. 작업 순서와 완료 기준

**M1 — 뼈대 (Claude, 1회 작업)**

- [ ] 저장소 구조, `schemas/` 3종, 샘플 `data/` 4종, `requirements.txt`, `README.md`
- [ ] `dedupe.py`, `validate.py`, `notify.py` + 플러그인 7종, `--dry-run` 동작
- [ ] `sources/epic_free.py`, `sources/rss.py`
- [ ] `docs/` 피드·설정 화면, GitHub API 커밋
- [ ] `CODEX.md`
- [ ] 완료 기준: 로컬에서 `python scripts/sources/epic_free.py | python scripts/dedupe.py | python scripts/notify.py --dry-run` 파이프가 돈다

**M2 — 연결 (사용자, 30분)**

- [ ] Pages 켜기(`main` / `/docs`), PAT 발급, 설정 화면에서 저장 1회 성공
- [ ] ntfy 앱 설치, 토픽 정하고 `notifiers.json`에 등록
- [ ] Codex 클라우드 환경 생성, 시크릿 등록, 수동 실행 1회로 feed 갱신·알림 확인

**M3 — 자동화 (사용자, 10분)**

- [ ] Automation 등록: 09:00 / 19:00 KST
- [ ] health 체크 Automation 등록: 매주 월 10:00
- [ ] 일주일 운영 후 `runs.json` 보고 소스·키워드 조정

**M4 — 확장 (필요할 때)**

- [ ] 검색 경로 켜기(도메인 허용 목록 확장)
- [ ] 카카오톡·이메일 채널 활성화
- [ ] 피드 화면 월간 통계, `bought` 집계

## 11. Codex Automation 프롬프트 (그대로 붙여넣기)

**메인 실행 (하루 2회)**

```markdown
이 저장소는 개인용 딜 알림 봇이다. 저장소 루트의 CODEX.md를 먼저 읽고, 거기 적힌 실행 순서를 한 번 수행한다.

요약하면:
1. data/config.json에서 enabled인 카테고리를 읽는다.
2. 카테고리별로 후보를 모은다. scripts/sources/ 아래 스크립트를 먼저 실행하고, config.search_hints와 keywords로 웹 검색을 보조로 쓴다. 마지막 실행(data/runs.json의 최신 at) 이후 올라온 것만 본다.
3. 후보를 data/feed.json 항목 형식으로 정리한다. 값을 모르면 null, 절대 지어내지 않는다.
4. python scripts/dedupe.py 로 새 항목만 남기고, config의 exclude·min_discount_pct·max_price_krw·마감일로 거른다.
5. feed.json·seen.json·runs.json을 갱신하고 python scripts/validate.py 를 통과시킨다.
6. python scripts/notify.py --since-run 을 실행해 알림을 보낸다.
7. data/ 아래 변경만 커밋·푸시한다. 메시지: codex: run <날짜 시각 KST> (+N new)

규칙:
- docs/, scripts/, schemas/는 수정하지 않는다. 문제가 있으면 runs.json의 errors에 적는다.
- 로그인·캡차·차단 우회를 시도하지 않는다. 403/429는 그 소스를 이번 실행에서 포기한다.
- 새 항목이 0건이면 정상이다. runs.json만 갱신하고 커밋한다.
- 작업이 끝나면 한 줄로 보고한다: 찾은 N건, 새 M건, 알림 K건, 오류 목록.
```

**health 체크 (주 1회)**

```markdown
data/runs.json의 최신 at을 확인한다. 36시간 이내면 아무것도 하지 않고 "정상"이라고만 보고한다.
36시간을 넘겼으면 python scripts/notify.py --health-alert 를 실행해 "딜봇이 N시간째 실행되지 않음" 알림을 보내고, 가능한 원인(최근 runs.json errors)을 한 줄로 보고한다. 파일은 수정하지 않는다.
```

**Claude Code에 줄 구현 지시 (M1 시작할 때)**

```markdown
이 저장소에 이 문서의 스펙대로 DealBot 뼈대를 구현해줘. 3절 저장소 구조, 4절 스키마, 5절 UI, 6절 실행 흐름(CODEX.md에 그대로 담기), 7절 알림 플러그인 7종, 8절의 백업용 GitHub Actions 워크플로(workflow_dispatch만)까지. 완료 기준은 10절 M1. 브랜치 claude/m1-scaffold에 작업하고 PR을 열어줘.
```
