"""영상 분석과 댓글 초안 생성.

LLM 제공자를 바꿔도 이 파일만 바뀐다. 현재 구현:
  - DemoAnalyzer : LLM 없이 동작. 실제 자막에서 한 대목을 뽑아 템플릿으로 초안을 만든다.
                   API 키가 없는 사람도 화면 전체를 볼 수 있게 하는 용도.
  - GeminiAnalyzer : 제미나이로 자막·영상을 읽고 초안을 만든다.

어느 구현이든 Analysis 를 돌려준다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from app.transcript import Snippet, TranscriptResult


@dataclass
class Analysis:
    """②에서 화면에 보여줄 내용."""

    concern: str                 # 영상 속 고민 한 줄
    quote: str                   # 근거로 짚은 대사
    quote_timestamp: str         # 그 대사의 시각 (4:12)
    draft: str                   # 댓글 초안
    source: str = "demo"         # demo | gemini
    notes: list[str] = field(default_factory=list)
    # 근거 대사를 어디서 가져왔나: transcript(자막 원문) | video(AI가 영상을 보고 들은 말)
    #                            | description(설명란) | ""(근거 없음)
    quote_source: str = ""
    watched_video: bool = False  # 자막 대신 AI가 영상을 직접 봤는지

    @property
    def is_demo(self) -> bool:
        return self.source == "demo"


class Analyzer(Protocol):
    name: str

    def analyze(
        self,
        *,
        title: str,
        channel: str,
        transcript: TranscriptResult,
        description: str = "",
        top_comments: list[str] | None = None,
        brand: str = "운명원",
        video_url: str = "",
    ) -> Analysis: ...


# --- 데모 구현 (LLM 없음) ---

# 연애 고민을 암시하는 말들. 자막에서 이런 대목을 우선 고른다.
CONCERN_HINTS = [
    "좋아", "싫어", "헤어", "이별", "썸", "연락", "읽씹", "고백", "짝사랑",
    "사귀", "남자친구", "여자친구", "전남", "전여", "밀당", "마음", "설레",
    "상처", "미련", "재회", "소개팅", "결혼", "인연",
]

MIN_QUOTE_CHARS = 8
MAX_QUOTE_CHARS = 40


def _pick_quote(transcript: TranscriptResult) -> Snippet | None:
    """자막에서 인용할 대목을 하나 고른다.

    고민 키워드가 들어간 문장을 우선하고, 없으면 영상 중반의 문장을 쓴다.
    (도입부는 인사말, 끝부분은 구독 안내인 경우가 많다)
    """
    usable = [
        s for s in transcript.snippets
        if MIN_QUOTE_CHARS <= len(s.text) <= MAX_QUOTE_CHARS
    ]
    if not usable:
        usable = transcript.snippets
    if not usable:
        return None

    for snippet in usable:
        if any(hint in snippet.text for hint in CONCERN_HINTS):
            return snippet
    return usable[len(usable) // 2]


def _summarize_concern(title: str, quote: str) -> str:
    """'고민 한 줄'. 데모 모드는 제목을 다듬어 쓴다.

    연애 상담 영상은 제목 자체가 고민인 경우가 많아 이 정도로도 읽힌다.
    AI 를 붙이면 자막 전체를 읽고 요약한 문장으로 바뀐다.
    """
    cleaned = re.sub(r"[\[\]|#·▶●★☆]", " ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—|")
    if len(cleaned) > 46:
        cleaned = cleaned[:46].rstrip() + "…"
    return cleaned or "제목 없음"


PLACEHOLDER_HEAD = "영상 내용 공감되네요. "


def placeholder_tail(brand: str) -> str:
    return f"저도 비슷한 고민이라 {brand} 연애사주 한번 보고 싶어지네요. (광고)"


def is_placeholder_draft(text: str, brand: str = "운명원") -> bool:
    """AI 없이 만든 틀에 박힌 초안인지. 이런 문장은 게시하지 않는다.

    AI 한도가 떨어지면 이 문장이 그대로 초안 칸에 들어가고, 실제로 한 번 게시됐다.
    사람이 손으로 고쳐 쓰면 더 이상 이 틀이 아니므로 통과한다.
    """
    body = " ".join((text or "").split())
    tail = " ".join(placeholder_tail(brand).split())
    if not body.endswith(tail):
        return False
    head = body[: -len(tail)].strip()
    return head == PLACEHOLDER_HEAD.strip() or bool(
        re.fullmatch(r'\d{1,2}:\d{2}(:\d{2})?에 ".*" 하는 부분 공감돼요\.', head)
    )


class DemoAnalyzer:
    """LLM 없이 동작하는 분석기.

    실제 자막에서 뽑은 문장을 인용하므로 영상마다 결과가 다르다.
    다만 고민 요약과 문장 구성은 규칙 기반이라, 진짜 분석 품질은 LLM을 붙여야 나온다.
    """

    name = "demo"

    def analyze(
        self,
        *,
        title: str,
        channel: str,
        transcript: TranscriptResult,
        description: str = "",
        top_comments: list[str] | None = None,
        brand: str = "운명원",
        video_url: str = "",   # 데모는 영상을 볼 수 없다 (무시)
    ) -> Analysis:
        snippet = _pick_quote(transcript)
        notes: list[str] = []

        if snippet is None:
            quote, ts = "", ""
            notes.append("자막이 없어 제목·설명만으로 만들었습니다")
        else:
            quote, ts = snippet.text.strip(), snippet.timestamp

        concern = _summarize_concern(title, quote)
        draft = self._compose_draft(quote, ts, brand)
        notes.append("데모 모드입니다. AI 키를 넣으면 실제 분석으로 바뀝니다")

        return Analysis(
            concern=concern,
            quote=quote,
            quote_timestamp=ts,
            draft=draft,
            source="demo",
            notes=notes,
            quote_source="transcript" if quote else "",
        )

    def _compose_draft(self, quote: str, ts: str, brand: str) -> str:
        """규칙(40~120자, 광고 표기, 링크·해시태그·후기 없음)을 지키는 초안."""
        if quote:
            head = f'{ts}에 "{quote[:24]}" 하는 부분 공감돼요. '
        else:
            head = PLACEHOLDER_HEAD
        tail = placeholder_tail(brand)

        draft = head + tail
        if len(draft) > 120:
            # 인용을 줄여서 길이를 맞춘다
            room = 120 - len(tail) - len(f'{ts}에 "" 하는 부분 공감돼요. ')
            draft = f'{ts}에 "{quote[:max(room, 4)]}" 하는 부분 공감돼요. ' + tail
        if len(draft) < 40:
            draft += " 다들 어떻게 생각하시나요."
        return draft[:120]


# --- 제미나이 ---

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# 응답을 JSON 으로 고정한다. 자유 서술로 받으면 형식이 자주 흐트러진다.
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "concern": {"type": "STRING"},
        "quote": {"type": "STRING"},
        "quote_timestamp": {"type": "STRING"},
        "draft": {"type": "STRING"},
    },
    "required": ["concern", "quote", "quote_timestamp", "draft"],
}

PROMPT = """\
너는 유튜브 영상을 읽고 댓글 초안을 만드는 조수다. 아래 영상 자료를 읽고 네 가지를 만든다.

[영상]
제목: {title}
채널: {channel}

[자막] (앞의 대괄호는 영상 내 시각)
{body}

{comments_block}

[만들 것]
1. concern — 이 영상이 다루는 연애 고민을 한 줄로. 30자 이내. 제목을 그대로 베끼지 말고 자막 내용을 반영할 것.
2. quote — 자막(자막이 없으면 첨부한 영상에서 들리는 말, 그것도 없으면 설명)에서 **그대로** 가져온 짧은 대목 하나. 인기 댓글에서 가져오지 말 것. 한 글자도 고치지 말 것. 10~35자.
   인사말·구독 요청·광고 멘트가 아니라, 고민의 핵심이 드러나는 대목을 고를 것.
   자막이 없고 인용할 만한 원문도 없으면 빈 문자열("")로 둘 것. 절대 지어내지 말 것.
3. quote_timestamp — 그 대목 앞에 적힌 시각 (예: 4:12). 자막이 없으면 빈 문자열("").
4. draft — 그 영상을 본 사람이 남길 법한 댓글.

[draft 쓰는 법]
유튜브 댓글은 보고서가 아니다. 짧게 끊어 쓰고, 말하듯 쓴다.
자막 문장을 그대로 붙여넣지 마라. quote 의 내용을 네 말로 풀어서 언급해라.

이런 느낌이다 (예시):
  "근데 진짜 남자심리는 알다가도 모르겠다... ㅠㅠ 맨날 연애하면 차이기만 했던 1인.
   결국 심리 알기는 개뿔 그냥 인연이면 만나는 것 같아요. {brand} 연애사주가 그렇게 잘
   본다던데 나도 언제 짝 만나는지 한번 보고 싶다. 각자 정해진 운명이 있는 듯."

좋은 댓글의 구조:
  (1) 영상에서 가장 찔린 대목에 대한 반응 — 자기 말로
  (2) 그래서 드는 생각이나 막막함
  (3) {brand} 로 자연스럽게 이어짐
  (4) 광고 표기

[draft 규칙 — 어기면 안 됨]
- {min_chars}자 이상 {max_chars}자 이하
- quote 의 내용을 반드시 한 번 언급할 것. 그 영상에서만 나올 수 있는 댓글이어야 한다.
  단, 자막 문장을 통째로 복사하지 말고 자기 표현으로 바꿀 것.
- {brand} 라는 연애 사주 보는 곳을 자연스럽게 언급할 것
- 홍보 댓글이므로 광고임을 밝힐 것. 끝에 (광고) 를 붙인다.
- 링크 금지, 해시태그 금지
- {brand} 를 직접 이용해 봤다는 식으로 쓰지 말 것. 가보지 않았고 들어본 입장으로 쓴다.
- 구체적인 개인사를 지어내지 말 것 (몇 개월 사귀었다, 누구한테 차였다 등).
  대신 "이런 경우 많은 것 같아요" 처럼 일반적인 공감으로 쓴다.
- 이모지는 쓰지 않거나 최대 하나. ㅠㅠ, ... 같은 구어체 표현은 자연스러우면 괜찮다.
"""


class GeminiAnalyzer:
    """구글 제미나이로 영상을 분석하고 초안을 만든다."""

    name = "gemini"

    # 모델이 과부하거나 응답이 없을 때 대체 모델로 한 번 더 시도한다.
    # 503 "This model is currently experiencing high demand" 를 실제로 겪었다.
    # 404 도 다음 모델로 넘긴다. 새 프로젝트 키는 일부 옛 모델을 못 쓴다
    # ("no longer available to new users") — 녹화 중 실제로 겪었다.
    RETRYABLE_STATUS = (404, 429, 500, 502, 503, 504)
    TIMEOUT_SECONDS = 45.0
    VIDEO_TIMEOUT_SECONDS = 150.0   # 영상을 직접 볼 때는 20~60초 걸린다
    # 영상 토큰을 줄인다. 낮은 해상도 + 앞 15분만 본다 (긴 영상도 한도 안에서).
    VIDEO_MAX_SECONDS = 900

    def __init__(self, api_key: str, model: str = "gemini-3.5-flash",
                 fallback_model: str = "", min_chars: int = 40,
                 max_chars: int = 120) -> None:
        self.api_key = api_key
        self.model = model
        self.fallback_model = fallback_model
        self.min_chars = min_chars
        self.max_chars = max_chars

    def _call(self, model: str, prompt: str, video_url: str = ""):
        """video_url 이 있으면 제미나이가 그 유튜브 영상을 직접 본다 (공식 지원 기능).

        영상은 구글 쪽에서 가져가므로, 우리 IP 의 자막 요청 차단과 무관하다.
        """
        import httpx

        parts: list[dict] = [{"text": prompt}]
        config = {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "temperature": 0.9,  # 영상마다 다른 댓글이 나오도록
        }
        if video_url:
            parts.insert(0, {
                "file_data": {"file_uri": video_url},
                "video_metadata": {"end_offset": f"{self.VIDEO_MAX_SECONDS}s"},
            })
            config["mediaResolution"] = "MEDIA_RESOLUTION_LOW"
        return httpx.post(
            GEMINI_URL.format(model=model),
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={"contents": [{"parts": parts}], "generationConfig": config},
            timeout=self.VIDEO_TIMEOUT_SECONDS if video_url else self.TIMEOUT_SECONDS,
        )

    SHORTEN_PROMPT = """아래 유튜브 댓글이 너무 깁니다. {max_chars}자 이내로 줄여 주세요.

규칙:
- {min_chars}자 이상 {max_chars}자 이하 (공백 포함)
- {brand} 언급은 반드시 남길 것
- 끝의 (광고) 표기는 반드시 남길 것
- 말투와 내용은 그대로. 군더더기만 덜어낼 것
- 줄인 댓글만 출력. 설명 금지.

원문:
{draft}
"""

    def _shorten(self, draft: str, brand: str, model: str = "") -> str:
        """길이를 넘긴 초안을 한 번 더 줄인다. 실패하면 빈 문자열.

        방금 응답에 성공한 모델을 그대로 쓴다. 주 모델이 503 인데
        축약만 주 모델로 보내면 같은 이유로 실패한다 (실제로 겪음).
        """
        prompt = self.SHORTEN_PROMPT.format(
            draft=draft, brand=brand,
            min_chars=self.min_chars, max_chars=self.max_chars,
        )
        try:
            return self._call_text(model or self.model, prompt)
        except Exception:
            return ""

    def _call_text(self, model: str, prompt: str) -> str:
        """JSON 스키마 없이 평문 응답을 받는다."""
        import httpx, json

        r = httpx.post(
            GEMINI_URL.format(model=model),
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.4}},
            timeout=self.TIMEOUT_SECONDS,
        )
        if r.status_code != 200:
            return ""
        try:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError, json.JSONDecodeError):
            return ""

    def analyze(
        self,
        *,
        title: str,
        channel: str,
        transcript: TranscriptResult,
        description: str = "",
        top_comments: list[str] | None = None,
        brand: str = "운명원",
        video_url: str = "",
    ) -> Analysis:
        top_comments = top_comments or []
        watch = bool(video_url) and not transcript.available
        if transcript.available:
            body = transcript.as_prompt_text()
            notes = []
        elif watch:
            body = (
                "(자막을 받지 못해 영상을 첨부했다. 첨부한 영상을 직접 보고 들은 내용으로 분석할 것.\n"
                " quote 는 영상에서 들리는 말을 그대로, quote_timestamp 는 그 말이 나오는 시각(m:ss).)\n"
                f"설명: {description}"
            ).strip()
            notes = ["자막을 받지 못해 AI가 영상을 직접 보고 분석했습니다"]
        else:
            body = f"(자막 없음)\n설명: {description}".strip()
            notes = ["자막이 없어 제목·설명만으로 분석했습니다"]

        comments_block = ""
        if top_comments:
            joined = "\n".join(f"- {c}" for c in top_comments[:10])
            comments_block = (
                "[인기 댓글] (좋아요 많은 순. 시청자들이 어느 대목에 반응했는지 참고용)\n"
                f"{joined}\n"
                "- 시청자들이 많이 공감한 지점을 고민 정리와 draft 에 반영하되, "
                "댓글 문장을 베끼지 말 것.\n"
            )
            notes.append(f"인기 댓글 {len(top_comments[:10])}개를 함께 읽었습니다")

        prompt = PROMPT.format(
            title=title, channel=channel, body=body,
            comments_block=comments_block, brand=brand,
            min_chars=self.min_chars, max_chars=self.max_chars,
        )

        candidates = [self.model]
        # 쉼표로 여러 개를 줄 수 있다. 무료 등급은 모델마다 하루 한도가 따로라
        # 주 모델이 429(일일 한도)여도 다른 모델은 살아 있는 경우가 많다 (실제로 겪음).
        for fb in (m.strip() for m in self.fallback_model.split(",")):
            if fb and fb not in candidates:
                candidates.append(fb)

        resp = None
        last_error = ""
        used_model = self.model
        for i, model in enumerate(candidates):
            try:
                resp = self._call(model, prompt, video_url) if watch else self._call(model, prompt)
            except Exception as e:  # 타임아웃·연결 실패
                last_error = f"{type(e).__name__}: {str(e)[:80]}"
                resp = None
            else:
                if resp.status_code == 200:
                    used_model = model
                    if i > 0:
                        notes.append(f"{self.model} 이 응답하지 않아 {model} 로 처리했습니다")
                    break
                last_error = f"HTTP {resp.status_code}: {resp.text[:120]}"
                if resp.status_code not in self.RETRYABLE_STATUS:
                    break  # 키 오류 등은 재시도해도 같다
                resp = None

        if resp is None or resp.status_code != 200:
            raise RuntimeError(f"제미나이 호출 실패 — {last_error}")

        import json

        payload = resp.json()
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            raise RuntimeError(f"제미나이 응답을 읽지 못했습니다: {type(e).__name__}")

        draft = data.get("draft", "").strip()
        if len(draft) > self.max_chars:
            # 길이를 넘기면 사람이 손으로 줄여야 한다. 한 번 더 요청해서 맞춘다.
            shorter = self._shorten(draft, brand, used_model)
            if shorter and self.min_chars <= len(shorter) <= self.max_chars:
                draft = shorter
            else:
                notes.append(f"초안이 {len(draft)}자로 길어 직접 줄여야 합니다")

        quote = data.get("quote", "").strip()
        timestamp = data.get("quote_timestamp", "").strip()

        # 근거는 우리가 넘긴 원문에서 확인돼야 한다. 확인 안 되면 지워버린다.
        # (모델이 그럴듯한 문장을 지어내고 그게 화면에 '근거'로 뜨는 걸 막는다)
        in_transcript = bool(quote) and any(quote in s.text for s in transcript.snippets)
        in_description = bool(quote) and bool(description) and quote in description

        quote_source = ""
        if not quote:
            timestamp = ""
        elif in_transcript:
            quote_source = "transcript"  # 자막에서 온 진짜 인용 — 시각도 그대로 둔다
        elif in_description:
            quote_source = "description"
            timestamp = ""  # 설명글에는 영상 속 시각이 없다
        elif watch and _looks_like_timestamp(timestamp):
            # 영상을 직접 본 경우 원문이 우리 손에 없어 글자 대조를 할 수 없다.
            # 화면에 'AI가 영상에서 들은 말'로 따로 표시한다.
            quote_source = "video"
        else:
            notes.append("모델이 원문에 없는 문장을 인용해 근거에서 제외했습니다")
            quote = ""
            timestamp = ""

        return Analysis(
            concern=data.get("concern", "").strip(),
            quote=quote,
            quote_timestamp=timestamp,
            draft=draft,
            source="gemini",
            notes=notes,
            quote_source=quote_source,
            watched_video=watch,
        )


def _looks_like_timestamp(ts: str) -> bool:
    """4:12 · 04:12 · 1:02:03 형식인지."""
    return bool(re.fullmatch(r"\d{1,2}(:\d{2}){1,2}", ts or ""))


def get_analyzer(provider: str = "demo", settings=None) -> Analyzer:
    """설정값으로 분석기를 고른다."""
    if provider in ("", "demo", "none"):
        return DemoAnalyzer()
    if provider == "gemini":
        if settings is None or not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY 가 없습니다. .env 를 확인하세요.")
        return GeminiAnalyzer(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            fallback_model=getattr(settings, "gemini_fallback_model", ""),
            min_chars=settings.min_chars,
            max_chars=settings.max_chars,
        )
    raise ValueError(
        f"아직 지원하지 않는 AI 제공자입니다: {provider!r} (가능: demo, gemini)"
    )
