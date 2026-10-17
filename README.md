# 딜봇 (DealBot)

내가 정한 분야·키워드의 특가, 포인트 적립, 할인 이벤트를 하루 몇 번 모아서 원하는 채널(ntfy 폰 푸시, Slack, Discord, Telegram, Pushover, 카카오톡, 이메일)로 보내 주는 개인용 봇이다. 서버는 없다.

- **수집·판단·알림 실행**: Codex Automation (클라우드). 매 실행마다 [`CODEX.md`](CODEX.md)를 따른다.
- **설정·피드 보기**: GitHub Pages (`docs/`). 폰 브라우저에서 편집한다.
- **상태**: 이 저장소의 `data/*.json`이 전부다. 되돌리기는 `git revert` 한 번이면 된다.

전체 설계는 [`SPEC.md`](SPEC.md)에 있다.

```
dealbot/
├── docs/            GitHub Pages: 피드(index.html), 설정(settings.html), 가이드(guide.html = MANUAL.md), app.js, style.css
├── index.html       Pages를 저장소 루트로 켰을 때 docs/로 넘겨 준다
├── tests/           Python unittest + node:test (GitHub Actions tests.yml)
├── data/            상태. Codex는 이 폴더만 커밋한다
│   ├── config.json      분야·키워드·소스·주기 (UI가 편집)
│   ├── notifiers.json   알림 채널 (UI가 편집, 토큰 없음)
│   ├── feed.json        최신 실행 결과(items, 매 실행 교체) + 알림 대기열(pending) + 샀음 기록(bought)
│   ├── seen.json        중복 판정 키 (30일)
│   ├── runs.json        실행 로그 (최근 50회, 걸러진 이유·사용자 피드백 포함)
│   └── playbook.md      검색 플레이북. Codex가 읽고, 매 실행 후 스스로 개선한다
├── scripts/
│   ├── run_deterministic.py  소스 실행 → 중복 제거 → 필터 → data/ 기록 (한 번의 수집)
│   ├── dedupe.py · filters.py · validate.py · notify.py
│   ├── review_run.py    실행 회고 (플레이북 개선 근거)
│   ├── sources/         epic_free.py, rss.py
│   └── notifiers/       채널 플러그인 (파일 하나 = 채널 하나)
├── schemas/         JSON Schema (UI와 validate.py가 같이 씀)
├── CODEX.md         Codex 운영 지침
└── .github/workflows/deterministic.yml   백업 실행기 (기본 꺼짐, 수동 실행만)
```

## 로컬에서 돌려 보기

Python 3.10 이상.

```bash
pip install -r requirements.txt

# 소스 → 중복 제거 → 필터 → 알림 미리보기 (아무것도 보내거나 쓰지 않음)
python scripts/sources/rss.py --all | python scripts/dedupe.py | python scripts/filters.py | python scripts/notify.py --dry-run

# 채널별 메시지 형식 미리보기 (꺼진 채널 포함)
python scripts/notify.py --dry-run --sample

# 실제 전송 1건 테스트 (해당 채널 환경변수 필요)
DEALBOT_NTFY_TOPIC=내-토픽 python scripts/notify.py --sample --channel ntfy

# 한 번의 수집을 기록 없이 미리보기
python scripts/run_deterministic.py --dry-run

# data/ 검증
python scripts/validate.py
```

`epic_free` 소스는 기본 설정에서 쓰지 않는다. 필요하면 설정 화면에서 카테고리의 소스로 체크하면 된다. `python scripts/sources/epic_free.py --category <id>`로 단독 실행할 수 있다.

UI는 저장소 루트에서 `python -m http.server`를 띄우고 `http://localhost:8000/docs/`로 열면 로컬 `data/`를 읽는다. 저장(커밋)은 토큰이 있어야 하고, 항상 GitHub의 `main`에 쓴다.

## 처음 설정 (M2, 약 30분)

### 1. GitHub Pages 켜기

저장소 **Settings → Pages → Build and deployment**에서 Source를 `Deploy from a branch`, Branch를 `main`, 폴더는 `/ (root)` 또는 `/docs` 중 아무거나 둔다. 1~2분 뒤 `https://<user>.github.io/dealbot/`에서 열린다. 루트로 두면 루트 `index.html`이 앱(`docs/`)으로 넘겨 준다(현재 설정).

> **공개 저장소 주의**: 이 저장소가 공개면 `data/`의 피드·설정·채널 대상이 누구에게나 보인다. 토큰은 원래 저장소에 없지만, **ntfy 토픽, Telegram chat_id, 이메일 주소도 notifiers.json의 `target`에 넣지 말고** 환경변수(`DEALBOT_NTFY_TOPIC`, `DEALBOT_TELEGRAM_CHAT_ID`, `DEALBOT_EMAIL_TO`)로 넣는다. `target`을 비워 두면 스크립트가 환경변수를 쓴다. 저장소를 비공개로 바꾸면 Pages는 GitHub Pro 이상에서만 동작하고, 피드 화면도 토큰을 넣어야 보인다.

### 2. UI용 토큰(PAT) 발급

GitHub **Settings → Developer settings → Fine-grained personal access tokens → Generate new token**에서 다음과 같이 만든다.

- Repository access: **Only select repositories → dealbot**
- Permissions: **Contents: Read and write** (나머지는 없음)
- Expiration: 90일

설정 화면에는 GitHub 항목이 없다. 저장소 주소는 페이지 URL에서 알아낸다. 처음 무언가를 저장할 때(설정 **저장**, 피드의 **샀음**·**무시**) 토큰 입력 창이 한 번 뜬다. 여기에 붙여 넣으면 그 브라우저의 localStorage에 기억된다. 토큰이 만료되거나 거절되면 다음 저장 때 창이 다시 뜬다. 아무 설정이나 한 번 저장해서 `ui: update config` 커밋이 생기는지 확인한다.

> 토큰을 페이지에 미리 넣어 둘 수는 없다. Pages는 공개 사이트라서, 넣어 두면 누구나 그 토큰으로 저장소에 쓸 수 있다.

### 3. 알림 채널

처음에는 **ntfy**를 추천한다. 무료이고 계정도 필요 없다.

1. 폰에 ntfy 앱(iOS/Android)을 설치한다.
2. 추측할 수 없는 토픽명을 정한다. 예: `dealbot-` 뒤에 무작위 16자.
3. 앱에서 그 토픽을 구독한다.
4. 토픽명을 Codex 시크릿 `DEALBOT_NTFY_TOPIC`에 넣는다(4단계).
5. 로컬에서 `DEALBOT_NTFY_TOPIC=<토픽> python scripts/notify.py --sample --channel ntfy`를 실행해 폰에 알림이 오는지 본다.

다른 채널의 시크릿은 아래 표와 같다. 쓰는 채널 것만 넣는다.

| 채널 | 환경변수 | 발급 |
| --- | --- | --- |
| ntfy | `DEALBOT_NTFY_TOPIC`, `DEALBOT_NTFY_TOKEN`(선택), `DEALBOT_NTFY_SERVER`(선택) | 위 절차 |
| Slack | `DEALBOT_SLACK_WEBHOOK` | api.slack.com/apps → Create App → Incoming Webhooks → 채널 선택 |
| Discord | `DEALBOT_DISCORD_WEBHOOK` | 채널 설정 → 연동 → 웹후크 → URL 복사 |
| Telegram | `DEALBOT_TELEGRAM_TOKEN`, `DEALBOT_TELEGRAM_CHAT_ID` | @BotFather로 봇 생성 → 봇에게 말 걸기 → `https://api.telegram.org/bot<토큰>/getUpdates`에서 chat.id 확인 |
| Pushover | `DEALBOT_PUSHOVER_TOKEN`, `DEALBOT_PUSHOVER_USER` | pushover.net에서 Application 생성(토큰), 대시보드의 User Key |
| 카카오톡 | `DEALBOT_KAKAO_REST_KEY`, `DEALBOT_KAKAO_REFRESH_TOKEN`, `DEALBOT_KAKAO_CLIENT_SECRET`(쓰는 경우) | 아래 절차 |
| 이메일 | `DEALBOT_SMTP_HOST`, `DEALBOT_SMTP_USER`, `DEALBOT_SMTP_PASS`, `DEALBOT_SMTP_PORT`(기본 587), `DEALBOT_EMAIL_TO` | Gmail: `smtp.gmail.com`, 2단계 인증 후 앱 비밀번호 |

#### 카카오톡 "나에게 보내기" 토큰 발급

1. [Kakao Developers](https://developers.kakao.com) → 내 애플리케이션 → 앱 추가.
2. **앱 키**의 REST API 키를 `DEALBOT_KAKAO_REST_KEY`에 넣는다.
3. **플랫폼 → Web → 사이트 도메인**에 `https://<user>.github.io`를 등록한다. 메시지 링크는 등록된 도메인만 허용된다. 그래서 알림은 피드 주소로 연결된다.
4. **카카오 로그인**을 활성화하고 Redirect URI에 `https://<user>.github.io/dealbot/`를 등록한다.
5. **동의항목**에서 "카카오톡 메시지 전송(talk_message)"을 사용으로 설정한다.
6. 브라우저에서 아래 주소를 열고 동의한다. 리다이렉트된 주소의 `code=` 값을 복사한다.
   ```
   https://kauth.kakao.com/oauth/authorize?client_id=<REST키>&redirect_uri=https://<user>.github.io/dealbot/&response_type=code&scope=talk_message
   ```
7. 토큰을 교환한다. 응답의 `refresh_token`을 `DEALBOT_KAKAO_REFRESH_TOKEN`에 넣는다.
   ```bash
   curl -X POST https://kauth.kakao.com/oauth/token \
     -d grant_type=authorization_code -d client_id=<REST키> \
     -d redirect_uri=https://<user>.github.io/dealbot/ -d code=<code>
   # 앱 보안 설정에서 Client Secret을 켰다면 -d client_secret=... 추가 + DEALBOT_KAKAO_CLIENT_SECRET 등록
   ```

refresh_token은 약 2개월 동안 유효하다. 만료되면 `notify.py`가 다른 켜진 채널로 "카카오 토큰 갱신 필요" 알림을 보낸다(하루 1회). 그때 6~7단계를 다시 한다.

### 4. Codex 클라우드 환경

1. Codex 웹에서 이 저장소를 **환경**으로 추가한다.
2. 셋업 스크립트에 `pip install -r requirements.txt`를 넣는다.
3. 인터넷 접근을 켜고 도메인 허용 목록에 다음을 넣는다.
   - GitHub: `github.com`, `api.github.com`
   - 알림: `ntfy.sh`, `hooks.slack.com`, `discord.com`, `api.telegram.org`, `api.pushover.net`, `kapi.kakao.com`, `kauth.kakao.com`
   - 소스: `www.ppomppu.co.kr`, `bbs.ruliweb.com`, `store-site-backend-static-ipv4.ak.epicgames.com`
   - 웹 검색을 쓰려면 검색 결과로 열 사이트도 허용해야 한다. 허용 목록이 좁으면 검색은 사실상 막힌다. 처음에는 RSS 위주로 돌리고, 검색은 목록을 넓힌 뒤 켠다.
4. 시크릿(환경변수)에 3단계 표의 변수를 넣는다.
5. Codex GitHub 앱이 `main`에 push할 수 있어야 한다. 브랜치 보호를 걸었다면 Codex 봇 계정을 예외로 둔다.
6. 수동으로 한 번 실행한다(아래 메인 프롬프트). `codex: run ...` 커밋이 생기고 피드 화면에 실행 기록이 뜨는지 확인한다.

## 자동 실행 (M3)

Codex Automation을 두 개 등록한다. 환경은 위에서 만든 `dealbot`이다.

**메인 실행**: 매일 09:00, 19:00 KST. 설정 화면의 "실행 시간"과 맞춘다.

```
이 저장소는 개인용 딜 알림 봇이다. 저장소 루트의 CODEX.md를 읽고, 거기 적힌 실행 순서(1~7단계)를 한 번 수행한다.

규칙:
- 판단이 필요한 건 2단계 웹 검색과 6단계 플레이북 개선뿐이다. 나머지는 CODEX.md에 적힌 스크립트를 그대로 실행한다.
- data/playbook.md를 읽고 따르며, 6단계에서 근거가 있을 때만 고친다.
- 값을 모르면 null. 절대 지어내지 않는다.
- docs/, scripts/, schemas/, CODEX.md는 수정하지 않는다. data/ 아래 변경만 커밋·푸시한다.
- 이미 끝났거나 마감이 config의 min_days_left일 이내인 이벤트는 고르지 않는다.
- 로그인·캡차·차단 우회를 시도하지 않는다. 403/429는 그 소스를 이번 실행에서 포기한다.
- 새 항목이 0건이면 정상이다. runs.json만 갱신하고 커밋한다.
- 끝나면 한 줄로 보고한다: 찾은 N건, 새 M건, 알림 K건, 오류 목록.
```

**health 체크**: 매주 월요일 10:00 KST.

```
data/runs.json의 runs[0].at을 확인한다. 36시간 이내면 아무것도 하지 않고 "정상"이라고만 보고한다.
36시간을 넘겼으면 python scripts/notify.py --health-alert 를 실행해 "딜봇이 N시간째 실행되지 않음" 알림을 보내고, 가능한 원인(최근 runs.json errors)을 한 줄로 보고한다. 파일은 수정하지 않는다.
```

실행 1회가 Codex 세션 1회다. 하루 2~4회가 현실적이다.

**백업 실행기**: Codex 사용량이 부족하거나 클라우드에서 국내 사이트가 막히면, Actions 탭의 `deterministic-run`을 수동으로 돌리거나 워크플로 파일의 `schedule`을 켠다. RSS와 에픽 같은 결정적 소스만 돈다. 시크릿은 저장소 **Settings → Secrets and variables → Actions**에 같은 이름으로 넣는다.

## 알림 규칙

| 우선순위 | 보내는 시점 |
| --- | --- |
| `instant` | 잡힌 실행에서 바로 보낸다. 조용한 시간이면 다음 실행으로 미룬다 |
| `daily` | 하루 첫 실행에서 전날까지 모인 것을 묶어 보낸다 |
| `weekly` | 주의 첫 실행(보통 월요일)에서 지난 주까지 모인 것을 묶어 보낸다 |

- 채널마다 "받을 우선순위"를 고른다. 채널마다 따로 기록하므로 한 채널이 실패해도 다음 실행에 그 채널만 다시 보낸다(48시간 이내 항목만).
- 메시지당 최대 `max_items_per_message`개, 한 번에 메시지 3개까지 보낸다. 넘치면 "외 N건, 피드에서 확인"으로 줄인다.
- 같은 소스가 3번 연속 실패하면 하루 1회 "소스 실패" 알림을 보낸다.

## 필터 규칙

`scripts/filters.py`가 수집 후에 적용한다.

- `exclude` 단어가 제목·요약에 있으면 제외한다.
- **RSS 소스**는 게시판 전체 글이 들어오므로, 카테고리 `keywords` 중 하나라도 제목·요약에 있어야 남긴다. 웹 검색과 에픽 결과는 이미 키워드로 찾은 것이라 이 검사를 하지 않는다.
- 할인율이 `min_discount_pct` 미만이면 제외한다. 할인율을 모르면 통과시킨다.
- 가격이 `max_price_krw`를 넘으면 제외한다. 가격을 모르면 통과시킨다.
- 마감일이 지났으면 제외한다.

## 채널 추가하기

`scripts/notifiers/<type>.py` 파일 하나를 만든다. `Notifier`를 상속하고 `type`, `required_env`, `render(msg)`, `deliver(payload)`를 구현하면 `notify.py`가 자동으로 찾는다. 그다음 `schemas/notifiers.schema.json`의 `type` enum과 `docs/app.js`의 `CHANNEL_TYPES`에 추가한다.

## 보안

- 토큰은 두 곳에만 둔다. 알림 토큰은 Codex 시크릿에, UI용 PAT는 내 브라우저 localStorage에 둔다. 저장소에는 토큰이 한 글자도 없어야 한다.
- `validate.py`는 `data/`에서 토큰·웹훅처럼 보이는 값이 나오면 실패한다. 실패하면 커밋되지 않는다.
- 요청 예절: 소스당 실행당 1회 요청하고, User-Agent는 `dealbot/1.0 (personal)`이다. 403과 429를 받으면 바로 포기한다.
