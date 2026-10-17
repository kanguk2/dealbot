# CLAUDE.md — 딜봇 개발 지침 (Claude Code 세션용)

이 파일은 이 저장소에서 작업하는 **모든 Claude 세션이 처음에 읽는 규칙**이다. 세션이 바뀌어도 같은 방식으로 작업이 이어지도록, 규칙을 바꾸거나 큰 결정을 내리면 이 파일도 같이 고친다.

- 설계 원본: [`SPEC.md`](SPEC.md). 사용자가 작성했고 역할 분담, 스키마, 실행 흐름, 마일스톤이 들어 있다.
- 사용자용 설치·운영 문서: [`README.md`](README.md)
- Codex 실행 지침: [`CODEX.md`](CODEX.md). 정기 실행은 GitHub Actions `dealbot.yml`이 하고, Codex(`openai/codex-action`)는 2단계 검색·6단계 회고만 맡는다(프롬프트 `.github/codex/`).
- 사용 설명서: [`MANUAL.md`](MANUAL.md). 상황별 사용법이다. `manual-writer` 서브에이전트만 고친다(2절 4번).
- 서브에이전트: `.claude/agents/manual-writer.md`(설명서), `.claude/agents/test-runner.md`(테스트)

## 1. 역할 경계 (가장 중요)

| 누가 | 무엇을 | 건드리는 곳 |
| --- | --- | --- |
| Claude (개발) | 코드·UI·스키마·문서 구현과 수정 | `docs/`, `scripts/`, `schemas/`, `*.md`, `.github/`, `requirements.txt` |
| GitHub Actions `dealbot.yml` + Codex (운영) | 하루 1회(09:00 KST) 수집·알림 실행, Codex가 웹 검색·플레이북 개선 | `data/feed.json`, `seen.json`, `runs.json`(스크립트를 통해), `data/playbook.md`(직접, CODEX.md 6단계 규칙) |
| 사용자 (웹 UI) | 설정 편집, 딜 상태 변경 | `data/config.json`, `data/notifiers.json`, `feed.json`의 `status` |

- Claude는 `data/` 파일의 **기본값과 구조만** 바꾼다. 운영 중 쌓인 데이터(feed, seen, runs)를 지우거나 다시 쓰지 않는다. 스키마가 바뀌어 마이그레이션이 필요하면 스크립트로 하고 PR에 적는다.
- `main`에는 Codex와 UI가 수시로 커밋한다. 작업 전에 항상 `git pull`부터 한다.
- Codex 쪽 규칙(CODEX.md)을 바꾸면 README의 "자동 실행" 프롬프트와 맞는지 같이 확인한다.

## 2. Git 작업 규칙

사용자 요청(2026-10-17): **모든 기능 추가와 수정은 커밋하고 바로 `main`에 push한다. 브랜치와 PR은 만들지 않는다.** 로컬에만 남겨 두지 않는다.

1. 시작할 때: `git checkout main && git pull --rebase` (Codex와 웹 UI가 `main`에 수시로 커밋한다).
2. 의미 단위로 커밋한다. 메시지는 `<type>: <요약>` 형식으로 쓴다. type은 `feat`, `fix`, `docs`, `refactor`, `chore`, `test` 중 하나다. 본문에 무엇을, 왜 바꿨는지 적는다. 마지막 줄에는 세션이 지정하는 `Co-Authored-By` 트레일러를 넣는다.
   - `codex: ...`(Codex 실행), `ui: ...`(웹 UI 저장), `actions: ...`(백업 워크플로) 접두어는 봇 전용이다. Claude는 쓰지 않는다.
3. **테스트는 `test-runner` 서브에이전트에게 맡긴다**(`.claude/agents/test-runner.md`). 사용자 요청(2026-10-17)이다. 코드를 바꾸면 커밋 전에 바뀐 동작을 프롬프트에 적어 실행한다. 서브에이전트가 테스트를 추가·수정하고, 전체 스위트와 뮤테이션 확인, 필요하면 화면 확인까지 돌려 보고한다. 실패나 버그 보고가 오면 메인 세션이 고치고 다시 맡긴다. 테스트 파일 변경도 같은 커밋에 넣는다.
4. 사용자에게 보이는 동작이 바뀌었으면 **`manual-writer` 서브에이전트**를 실행한다(`.claude/agents/manual-writer.md`). 바뀐 동작에는 UI, 설정 항목, 알림 규칙, 채널, 소스, Codex 실행 방식, 설치 절차가 포함된다. 서브에이전트가 `MANUAL.md`를 갱신하면 커밋한다. 설명서를 메인 세션에서 직접 쓰지 않는다. 두 서브에이전트는 독립적이라 병렬로 실행해도 된다.
   - 에이전트 정의가 목록에 보이지 않으면 general-purpose 에이전트에게 "`.claude/agents/<name>.md`를 읽고 그 지침대로 수행하라"고 시킨다.
5. push 전에 `git pull --rebase`를 한 번 더 하고, `git push origin main`을 실행한다. 거절되면 다시 rebase한 뒤 push한다.
6. 작업이 끝나면 맨 아래 **작업 로그**에 한 줄을 추가해 같이 커밋한다.
7. force push, 히스토리 재작성, `data/` 운영 데이터 되돌리기는 사용자에게 먼저 묻는다.

### 이 PC 환경 메모 (Windows)

- `python`은 MS Store 스텁이라 동작하지 않는다. `py`를 쓰거나 venv를 만들어 쓴다.
  ```bash
  py -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
  ```
  `.venv/`는 gitignore돼 있다.
- `gh` CLI가 없다. GitHub API가 필요하면(Pages 상태 확인 등) 토큰을 `git credential fill`(host=github.com)로 얻고, 출력하거나 파일에 쓰지 않는다.
- 로컬 git 계정은 `kevinkanguk`(협업자 권한)이고, 저장소 소유자는 `kanguk2`다.
- `core.autocrlf=true` 환경이다. `.gitattributes`(`eol=lf`)가 있으니 줄바꿈은 신경 쓰지 않아도 된다.
- 셸 heredoc 안에 따옴표가 많은 긴 파일을 넣으면 깨진다. 파일은 Write 도구로 만든다.

## 3. 코드 규칙

- **Python**: 3.10+. 의존성은 표준 라이브러리 + `jsonschema` + `tzdata`만 쓴다. 새 패키지가 꼭 필요하면 PR에 이유를 적는다. HTTP는 `common.http_request`를, 파일 I/O는 `common.load_data/save_data`를 쓴다. 출력은 `common.setup_io()`로 UTF-8을 강제한다.
- 스크립트는 모두 CLI로 단독 실행할 수 있어야 하고, `--help`가 동작해야 한다. 결과는 stdout(JSON), 진행 로그와 경고는 stderr로 보낸다.
- **결정적인 일은 스크립트에 둔다.** Codex(LLM)가 판단할 자리는 "무엇을 찾을지"(웹 검색) 하나뿐이다. 새 규칙이 생기면 CODEX.md에 문장으로 쓰지 말고 스크립트로 만든다.
- **UI**: 프레임워크·빌드 없이 `docs/`의 HTML 2장 + `app.js` + `style.css`로 만든다. 외부 CDN을 쓰지 않는다. 폰 폭(390px)에서 가로 스크롤이 생기면 안 된다. 다크 모드는 CSS 변수로 처리한다.
- 사용자에게 보이는 문구(UI, 알림, README, CODEX.md)는 한국어로, 코드 주석과 식별자는 영어로 쓴다.
- **값을 지어내지 않는다.** 모르는 가격·할인율·날짜는 `null`이다. 파서가 애매하면 안 뽑는 쪽을 택한다(예: "100% 당첨"을 할인율로 보지 않음).
- **시크릿**: 토큰·웹훅은 환경변수에만 둔다. 저장소, 예시, 테스트 데이터에도 넣지 않는다. 저장소가 공개이므로 ntfy 토픽, chat_id, 이메일 주소 같은 식별자도 환경변수를 권장한다.

### 같이 고쳐야 하는 묶음 (하나만 고치면 깨진다)

| 바꾸는 것 | 같이 고칠 곳 |
| --- | --- |
| 데이터 필드 | `schemas/*.schema.json`, SPEC.md §4, 쓰는 스크립트, `docs/app.js` |
| 스키마 키워드 | `docs/app.js`의 미니 검증기는 일부 키워드만 지원한다(파일 안 주석 참고). 새 키워드를 쓰면 검증기도 구현한다 |
| 알림 채널 추가 | `scripts/notifiers/<type>.py`, `notifiers.schema.json`의 type enum, `app.js`의 `CHANNEL_TYPES`, README 시크릿 표, 워크플로 env |
| 소스 추가 | `scripts/sources/<name>.py`(`fetch(config, arg, since)`), `app.js`의 `sourceOptions`/`sourceName`, README의 Codex 도메인 허용 목록 |
| 실행 순서 | `CODEX.md`, `.github/workflows/dealbot.yml`, `.github/codex/*.md`, README "자동 실행 연결" |
| 실행 시간 | `dealbot.yml`의 cron(UTC), `data/config.json` `schedule.times`(KST), README |
| 사용자 관심사 (`interests.json`) | `docs/app.js` picks·☆ 관심·설정 관심사, `review_run` interest findings, CODEX.md 2·6단계, `.github/codex/search.md` |
| feed.json 구조 (`items`/`pending`/`bought`) | `run_deterministic.replace_feed`, `notify.run_since`/`prune_pending`, `docs/app.js` 피드·통계, `tests/test_pipeline.py` |
| 플레이북 섹션·한도 | `data/playbook.md`, `review_run.PLAYBOOK_SECTIONS`/`PLAYBOOK_LIMIT`, CODEX.md 6단계 |
| 사용자에게 보이는 동작 | `MANUAL.md` (manual-writer 서브에이전트), 가이드 탭은 MANUAL.md를 그대로 렌더링한다 |

## 4. 테스트 방법

**자동 테스트가 기본이다.** 기능을 추가하거나 고치면 테스트도 같이 추가하고, 커밋 전에 전부 돌린다. 실행은 `test-runner` 서브에이전트가 맡는다(2절 3번). 아래는 그 서브에이전트와 사람이 쓰는 명령이다. 사용자 요청(2026-10-17): "말한 것들이 제대로 동작하는지 테스트를 작성하고 돌린다."

```bash
python -m unittest discover -s tests        # Python 52+개 (단위 + data 임시 폴더 end-to-end)
node --test tests/js/app.test.mjs           # UI 로직 (검증기, 마크다운, 통계 등)
python scripts/validate.py                  # 커밋된 data/ 검증
```

- GitHub Actions `tests.yml`이 push·PR마다 같은 것을 돌린다(`data/`만 바뀐 봇 커밋은 제외).
- 테스트용 장치: `DEALBOT_DATA_DIR`(임시 data 폴더), `DEALBOT_NOW`(현재 시각 고정), `DEALBOT_HTTP_LOG`(HTTP를 보내지 않고 파일에 기록). 새 테스트는 `tests/helpers.py`의 `DataDirTest`를 쓴다.
- 테스트가 실제로 잡는지 의심되면 코드를 일부러 망가뜨려 실패하는지 확인한다(뮤테이션 확인).

수동 확인용 명령은 아래와 같다. 상태가 바뀌는 수동 테스트는 **저장소를 임시 폴더에 복사해서** 돌린다.

```bash
python scripts/validate.py
python scripts/sources/rss.py --all | python scripts/dedupe.py | python scripts/notify.py --dry-run
python scripts/notify.py --dry-run --sample          # 7개 채널 형식 전부
python scripts/run_deterministic.py --dry-run

# 복사본에서: 수집 → 다음 날 daily 묶음 확인
DEALBOT_NOW=2026-10-17T11:40:00+09:00 python scripts/run_deterministic.py
DEALBOT_NOW=2026-10-18T09:01:00+09:00 DEALBOT_NTFY_TOPIC=x python scripts/notify.py --since-run --dry-run
```

- 실제 전송 테스트는 무작위 이름의 ntfy 토픽으로만 한다(`DEALBOT_NTFY_TOPIC=dealbot-test-<random>`). 다른 채널은 사용자 시크릿이 없으니 dry-run으로 확인한다.
- UI는 저장소 루트에서 `python -m http.server`를 띄우고 `/docs/`를 연다. headless Chrome 스크린샷으로 확인할 수 있다(`chrome --headless=new --window-size=500,1400 --screenshot=...`). headless Chrome은 창 폭 500px 미만을 잘라서 찍으므로 500 이상으로 찍는다.
- JS 검증기는 Node `vm`에 `app.js`를 올려서 `validate(schema, data)`를 직접 호출해 테스트한다.

## 5. 현재 상태와 결정 이력

### 완료
- **M1 뼈대** (PR #1 머지됨. 이후로는 main 직접 push): 스키마 5종, 스크립트, 소스 2종, 알림 7종, Pages UI, CODEX.md, README, 백업 워크플로

### 스펙과 다르게 정한 것 (이유 포함)
- **피드는 실행마다 통째로 교체**: 사용자 선택(2026-10-17). `feed.items`는 최신 실행의 새 딜만 담는다. 묶음 알림은 `feed.pending` 대기열, 샀음 기록은 `feed.bought`(200건)로 남긴다. 이전 페이지의 무시·샀음은 `runs[0].user_feedback`로 넘어가 검색 학습에 쓰인다.
- **마감 필터**: 사용자 요청. `config.min_days_left`(기본 1)일 이내 마감과 이미 끝난 딜은 수집·표시·알림 모두에서 제외한다. 마감일을 모르면 통과시킨다.
- **검색 플레이북 자기개선**: 사용자 요청. `data/playbook.md`를 Codex가 매 실행 2단계에서 읽고 6단계에서 `review_run.py` 근거로 최대 3곳 고친다. CODEX.md는 고정 규칙이고, 플레이북이 학습되는 부분이다.
- **설정 화면에 GitHub 연결란 없음**: 사용자 요청. 저장소는 URL에서 알아내고, PAT는 처음 저장할 때 대화상자로 한 번 받는다. 공개 Pages라서 토큰을 페이지에 넣을 수 없다.
- **피드 자동 갱신**: 3분마다, 그리고 탭에 돌아올 때 runs.json을 확인한다.
- **가이드 탭**: `docs/guide.html`이 MANUAL.md를 렌더링한다. 외부 라이브러리 없이 `app.js`의 작은 마크다운 렌더러를 쓴다. MANUAL.md에 새 문법(중첩 표, 이미지 등)을 쓰면 렌더러와 테스트도 같이 고친다.
- **Pages 소스**: 사용자가 `main` / 루트로 켰다. 루트 `index.html`이 `docs/`로 넘겨 준다. `/docs` 소스로 바꿔도 동작한다.
- **게임 카테고리 제외**: 사용자 요청(2026-10-17). 기본 카테고리는 `points`(포인트·적립) 하나다. `epic_free.py`는 선택 소스로 남겨 두었다.
- 뽐뿌 이벤트 게시판 RSS가 2024년 이후 갱신되지 않아 `ppomppu_coupon`(쿠폰 게시판)으로 바꿨다. `ppomppu_hotdeal`, `ruliweb_hotdeal`은 등록만 해 두었다.
- 수집 단계(소스 → dedupe → filter → 기록)를 `run_deterministic.py`로 묶었다. Codex는 웹 검색 결과를 `.tmp/search.json`에 쓰고 `--extra`로 넘긴다.
- RSS 소스는 카테고리 키워드가 하나라도 맞아야 남긴다. 할인율·가격을 모르면 필터를 통과시킨다.
- 알림 상태는 채널별로 feed 항목 `notified`에 기록한다. 그래서 별도 상태 파일 없이 daily/weekly 묶음과 재시도가 동작한다. instant는 48시간 창 안의 항목만 보낸다.
- ntfy, Telegram, 이메일 대상은 환경변수가 `target`보다 우선한다(공개 저장소 대응).
- `validate.py`는 config·notifiers에서 token, webhook, secret, password, api_key 같은 단어를 금지한다. feed·seen·runs는 자격 증명처럼 생긴 값만 검사한다(딜 제목의 오탐을 피하려고).

### 남은 일
- **M2·M3 (사용자)**: README "처음 설정"과 "자동 실행" 참고. Pages는 켜짐(main/루트). PAT, ntfy, Codex 환경·시크릿·Automation 등록이 남음
- 아이디어: 설정 화면에서 플레이북 읽기/편집, 피드에서 "봤음" 표시
- **M4 (필요할 때)**: 검색 경로 켜기(도메인 허용 목록 확장), 카카오·이메일 활성화, 통계 고도화
- **미검증**: ntfy 외 채널의 실제 전송, Pages에서 PAT로 커밋하는 흐름(머지 후 사용자 확인 필요)

## 6. 작업 로그

새 작업이 끝날 때마다 한 줄씩 추가한다: `YYYY-MM-DD · 브랜치/PR · 무엇을 · 비고`

- 2026-10-17 · main · SPEC.md 추가(원본 파일명 `딜봇(DealBot) 구현 스펙 — Codex 작업 지시서.md`에서 이름 변경)
- 2026-10-17 · claude/m1-scaffold · PR #1 · M1 뼈대 전체 구현, 게임 카테고리 제외, CLAUDE.md 작성 · Python 파이프라인·ntfy 실전송·UI 렌더링 확인, 다른 채널 실전송은 미검증
- 2026-10-17 · claude/m1-scaffold · PR #1 · manual-writer 서브에이전트로 MANUAL.md 첫 작성. 서브에이전트가 찾은 문제 수정(ntfy·Pushover·카카오 "외 N건" 누락, 워크플로 env 3개 누락, README 미리보기에 filters.py 누락) · 35건 메시지로 넘침 문구 확인
- 2026-10-17 · claude/m1-scaffold · PR #1 · 설정에서 GitHub 연결란 제거(첫 저장 때 토큰 대화상자), 피드 실행마다 교체·자동 갱신, 마감 필터(min_days_left), 검색 플레이북 자기개선(review_run.py), 가이드 탭, 테스트 스위트(Python 52·JS 10)와 tests.yml · 뮤테이션 확인으로 테스트가 실제로 잡는 것 확인
- 2026-10-17 · main · PR 없이 main 직접 push로 전환, test-runner 서브에이전트 추가 · 사용자 요청
- 2026-10-17 · main · UI를 Flight Watch(gagulproject.github.io/flight-price-tracker) 스타일로 재디자인(히어로 통계, 딜 찾기 패널, 카드 그리드, 실행 기록 차트), 무시가 대기 중 묶음 알림에 반영 안 되던 버그 수정, 더 보기 hidden 버그 수정 · test-runner: Python 53·JS 18 통과, 500/1280px 화면 확인. 샀음 표시는 묶음 알림을 막지 않는다(무시만 막음)
