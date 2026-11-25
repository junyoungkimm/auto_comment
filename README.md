# 댓글 연상 및 자동화 프로젝트

유튜브 연애 상담 영상의 맥락을 읽고, 시청자 말투의 댓글 초안을 만들어, 계정의 크롬 창에서 한 글자씩 입력해 게시하는 로컬 대시보드.

(주)제이지그룹 AI PM 과제 · TRACK 2 제출물. 설계 판단과 근거는 [docs/제작의도.md](docs/제작의도.md)에 있습니다.

```
STEP 1 영상              STEP 2 분석과 초안                STEP 3 댓글 달기
채널 최신 영상       →   자막(없으면 AI가 영상을 직접 봄)  →  계정 자동 배정 (계정1~3)
링크 직접 입력           + 인기 댓글을 읽고 고민 한 줄      계정 크롬 창이 열리고
뜨는 연애 영상 찾기      장면 인용 + 댓글 초안              한 글자씩 입력 → 게시
                         규칙 실시간 검사                   내 댓글 확인 → 기록
```

## 설정 없이 바로 실행

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m playwright install chrome   # 처음 한 번 (크롬이 이미 있으면 생략 가능)
.\.venv\Scripts\python.exe -m app.server
```

→ http://127.0.0.1:8000

**영상 목록은 API 키 없이 진짜로 동작합니다** (유튜브 공식 RSS). AI 키가 없으면 규칙 기반 데모 결과를 보여주고 `데모 데이터` 배지가 뜹니다. 데모 초안은 게시할 수 없습니다.

## 실제로 쓰려면

### 1. AI 키 (분석 · 초안)

[Google AI Studio](https://aistudio.google.com/apikey)에서 무료로 발급합니다. `.env.example`을 `.env`로 복사하고 넣으세요.

```
GEMINI_API_KEY=...
```

> 무료 등급은 **모델·프로젝트마다 하루 한도**가 있습니다. 한도가 다 찼을 때 새 키를 만들려면 **새 프로젝트**에서 만들어야 합니다. 같은 프로젝트의 새 키는 한도를 공유합니다.

### 2. 계정 (크롬 프로필) — 자동 입력 게시

계정마다 **유튜브 채널이 있는 서로 다른 구글 계정**이 필요합니다. 필수는 계정1 하나입니다.

구글은 **자동 제어 중인 브라우저에서의 로그인**을 막으므로, 처음 로그인은 일반 크롬으로 합니다.

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="$PWD\profiles\계정1"
```

열린 창에서 로그인하고 창을 닫은 뒤, 자동 제어로 열어도 로그인이 유지되는지 확인합니다.

```powershell
.\.venv\Scripts\python.exe scripts\setup_profile.py 계정1 --check
```

계정2·3도 같은 방법입니다. 준비되지 않은 계정은 화면에서 `(준비 안 됨)`으로 표시되고 자동 배정에서 빠집니다.

### 3. 공식 API 권한 — 게시 확인 · 인기 댓글 · 키워드 검색 · API 게시

자동 입력 게시만으로도 동작하지만, API 권한이 있으면 **게시한 댓글이 실제로 공개됐는지** 대조하고, 인기 댓글과 '연애' 키워드 검색을 쓸 수 있습니다.

1. [프로젝트 생성](https://console.cloud.google.com/projectcreate)
2. [YouTube Data API v3 사용 설정](https://console.cloud.google.com/apis/library/youtube.googleapis.com) — OAuth 클라이언트와 **같은 프로젝트**
3. [대상 → 테스트 사용자](https://console.cloud.google.com/auth/audience)에 계정 이메일 추가 — 빠뜨리면 `403 access_denied`
4. [클라이언트 → OAuth 클라이언트 ID](https://console.cloud.google.com/auth/clients) → **데스크톱 앱** → JSON을 `secrets/client_secret.json`으로 저장

```powershell
.\.venv\Scripts\python.exe scripts\auth_youtube.py 계정1
```

> 앱이 테스트 상태면 토큰이 **7일 후 만료**됩니다. 만료되면 위 명령을 다시 실행하세요.

## 시연 전 점검

```powershell
.\.venv\Scripts\python.exe scripts\preflight.py   # 게시 조건 점검 (실제 게시 없음)
.\.venv\Scripts\python.exe scripts\warmup.py      # 자막 미리 받아 캐시 (IP 차단 예방)
```

자막이 차단돼도 AI가 영상을 직접 보고 분석하므로 시연은 진행됩니다.

## 운영 규칙 (코드에서 강제)

- 댓글 40~120자, 링크·해시태그 금지, 운명원 이용 후기 조작 금지, 광고 표기 필수
- AI 없이 만든 임시 문구는 게시 금지
- **영상당 댓글 1개** (어느 계정이든), **하루 게시 상한 10개** (계정 합계)
- 기록: 언제 · 어느 영상에 · 어느 계정으로 · 무슨 댓글을 · 성공/실패(사유 + 화면 캡처)

어긴 게 있으면 게시 버튼이 꺼지고, 서버도 한 번 더 거절합니다.

## 설정

`.env` (전부 선택, `.env.example` 참고)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `GEMINI_API_KEY` | — | 없으면 데모 모드 |
| `AGENT_GEMINI_MODEL` | `gemini-3.5-flash` | 분석 모델 |
| `AGENT_GEMINI_FALLBACK` | `gemini-2.5-flash,gemini-3.5-flash-lite` | 주 모델 실패 시 차례로 |
| `AGENT_GEMINI_WATCH_VIDEO` | `true` | 자막이 없으면 AI가 영상을 직접 봄 |
| `AGENT_CHANNELS` | — | 채널 ID 또는 `@핸들`, 쉼표 구분 |
| `YOUTUBE_API_KEY` | — | 없으면 계정의 OAuth 토큰을 씀 |
| `AGENT_MIN_CHARS` / `AGENT_MAX_CHARS` | `40` / `120` | 댓글 길이 |
| `AGENT_DAILY_MAX_COMMENTS` | `10` | 하루 게시 상한 (계정 합계) |
| `AGENT_REQUIRE_DISCLOSURE` | `true` | 광고 표기 강제 |
| `AGENT_RISING_MIN_VIEWS` / `MAX_VIEWS` / `MIN_VPH` | `1000` / `5000` / `150` | 뜨기 직전 영상 기준 |
| `AGENT_PROFILES` | `계정1,계정2,계정3` | 계정(크롬 프로필) 이름 |
| `AGENT_CHROME_PATH` | 자동 탐색 | 크롬 실행 파일 |
| `AGENT_DATA_DIR` | `./data` | 기록·캡처 위치 (테스트용 기록을 실제 기록과 분리할 때) |

## 구조

```
app/
  feed.py          공식 RSS로 영상 목록 · 시간당 조회수 · 링크 파싱 · oEmbed
  discover.py      '연애' 키워드로 뜨기 직전 영상 찾기 (search.list, 초안까지만)
  topics.py        연애 주제 판별
  transcript.py    자막 수집 (캐시 · 요청 간격)
  comments.py      인기 댓글 (commentThreads.list)
  llm.py           제미나이 분석 · 영상 직접 보기 · 대체 모델 · 데모 분석기
  rules.py         길이 · 링크 · 해시태그 · 후기 조작 · 광고 표기 · 게시 제한
  profiles.py      계정 상태 · 돌아가며 배정
  browser_post.py  계정 크롬 창에서 한 글자씩 입력 → 게시 → 확인 (Playwright)
  youtube_post.py  commentThreads.insert 게시 · 내 댓글 찾기
  browser.py       --user-data-dir 로 계정 크롬 창 열기
  capture.py       실패 순간 화면 캡처
  storage.py       활동 기록 (JSONL)
  google_auth.py   OAuth 토큰 관리
  server.py        FastAPI
web/               대시보드 (빌드 과정 없음)
scripts/           setup_profile · auth_youtube · warmup · preflight
```

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest
```

유튜브에 글을 올리거나 AI를 호출하지 않습니다. 외부 호출은 전부 가짜 응답으로 대체합니다.

## 비밀 값

`.env`, `secrets/`, `profiles/`(로그인 세션), `data/`(기록·캡처)는 git에서 제외되어 있습니다.

## 사용한 오픈소스

코드를 복사해 온 것은 없고, 아래 라이브러리를 의존성으로 설치해 사용합니다. 각 라이선스를 따릅니다.

| 오픈소스 | 버전(개발 시) | 라이선스 | 쓰는 곳 |
|---|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | 0.165 | MIT | 로컬 대시보드 서버 |
| [Uvicorn](https://github.com/encode/uvicorn) | 0.54 | BSD-3-Clause | 서버 실행 |
| [Pydantic](https://github.com/pydantic/pydantic) | 2.14 | MIT | 요청 데이터 검증 |
| [HTTPX](https://github.com/encode/httpx) | 0.28 | BSD-3-Clause | RSS · oEmbed · Gemini · Data API 호출 |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | 1.2 | BSD-3-Clause | `.env` 설정 읽기 |
| [Playwright for Python](https://github.com/microsoft/playwright-python) | 1.65 | Apache-2.0 | 계정 크롬 창 열기 · 한 글자씩 입력 · 게시 확인 |
| [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) | 1.2 | MIT | 자막 수집 |
| [google-api-python-client](https://github.com/googleapis/google-api-python-client) | 2.202 | Apache-2.0 | YouTube Data API (게시 · 인기 댓글 · 검색) |
| [google-auth](https://github.com/googleapis/google-auth-library-python) · [google-auth-oauthlib](https://github.com/googleapis/google-auth-library-python-oauthlib) · [google-auth-httplib2](https://github.com/googleapis/google-auth-library-python-httplib2) | 2.63 · 1.5 · 0.4 | Apache-2.0 | OAuth 인증 · 토큰 갱신 |
| [pytest](https://github.com/pytest-dev/pytest) | 9.2 | MIT | 테스트 |
| [IBM Plex Sans KR · IBM Plex Mono](https://github.com/IBM/plex) | — | SIL OFL 1.1 | 화면 글꼴 (Google Fonts로 불러옴) |

### 사용한 외부 서비스

오픈소스는 아니지만 아래 공식 서비스를 각 약관에 따라 사용합니다.

| 서비스 | 쓰는 곳 |
|---|---|
| [YouTube RSS 피드 · oEmbed](https://www.youtube.com/) | 영상 목록 · 링크 영상 정보 (키 불필요) |
| [YouTube Data API v3](https://developers.google.com/youtube/v3) | 댓글 게시 · 공개 확인 · 인기 댓글 · '연애' 키워드 검색 |
| [Gemini API](https://ai.google.dev/) | 영상 분석 · 고민 정리 · 댓글 초안 (유튜브 영상 직접 입력 포함) |

### AI 도구

개발 과정에서 AI 코딩 도구(Claude Code)를 사용했습니다. 과제 안내서상 AI 도구 사용에는 제한이 없습니다.
