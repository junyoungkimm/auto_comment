"""영상 자막을 가져온다.

과제 요구: "AI가 자막(없으면 제목·설명)과 인기 댓글을 읽고".
자막은 API 키 없이 가져올 수 있다. 자막이 없으면 제목·설명으로 폴백한다.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import CouldNotRetrieveTranscript

from app.config import PROJECT_ROOT

# 유튜브는 자막 요청이 몰리면 IP 를 막는다 (IpBlocked).
# 한 번 받은 자막은 디스크에 두고, 새로 받을 때는 간격을 둔다.
CACHE_DIR = PROJECT_ROOT / "data" / "transcripts"
MIN_INTERVAL_SECONDS = 1.5

_last_request = 0.0
_throttle_lock = threading.Lock()

# 한국어를 우선하고, 없으면 영어, 그 다음 아무거나
PREFERRED_LANGUAGES = ("ko", "ko-KR", "en", "en-US")


@dataclass(frozen=True)
class Snippet:
    start: float
    text: str

    @property
    def timestamp(self) -> str:
        """4:12 형식. 댓글에서 장면을 인용할 때 쓴다."""
        total = int(self.start)
        return f"{total // 60}:{total % 60:02d}"


@dataclass
class TranscriptResult:
    video_id: str
    snippets: list[Snippet] = field(default_factory=list)
    language: str | None = None
    is_generated: bool | None = None
    error: str | None = None
    cached: bool = False

    @property
    def available(self) -> bool:
        return bool(self.snippets)

    @property
    def full_text(self) -> str:
        return " ".join(s.text for s in self.snippets)

    def as_prompt_text(self, max_chars: int = 6000) -> str:
        """타임스탬프를 붙인 형태로 만든다. AI가 장면을 짚을 수 있게."""
        lines = [f"[{s.timestamp}] {s.text}" for s in self.snippets]
        out = "\n".join(lines)
        if len(out) <= max_chars:
            return out
        # 앞뒤를 남기고 가운데를 줄인다 (도입부와 결론이 보통 중요)
        head = out[: int(max_chars * 0.6)]
        tail = out[-int(max_chars * 0.3) :]
        return f"{head}\n\n...(중략)...\n\n{tail}"


def _cache_path(video_id: str) -> Path:
    return CACHE_DIR / f"{video_id}.json"


def load_cached(video_id: str) -> TranscriptResult | None:
    """받아둔 자막이 있으면 읽는다. 성공한 것만 캐시하므로 실패는 재시도된다."""
    path = _cache_path(video_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TranscriptResult(
            video_id=video_id,
            snippets=[Snippet(start=s["start"], text=s["text"]) for s in data["snippets"]],
            language=data.get("language"),
            is_generated=data.get("is_generated"),
            cached=True,
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_cache(result: TranscriptResult) -> None:
    if not result.available:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(result.video_id).write_text(
        json.dumps(
            {
                "language": result.language,
                "is_generated": result.is_generated,
                "snippets": [{"start": s.start, "text": s.text} for s in result.snippets],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _throttle() -> None:
    """연속 요청 사이에 최소 간격을 둔다 (IP 차단 예방)."""
    global _last_request
    with _throttle_lock:
        wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def fetch_transcript(
    video_id: str,
    languages: tuple[str, ...] = PREFERRED_LANGUAGES,
    use_cache: bool = True,
) -> TranscriptResult:
    """자막을 가져온다. 실패해도 예외를 던지지 않고 error 에 사유를 담는다."""
    if use_cache:
        cached = load_cached(video_id)
        if cached is not None:
            return cached

    _throttle()
    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(video_id, languages=languages)
    except CouldNotRetrieveTranscript as e:
        name = type(e).__name__
        hint = ""
        if name in ("IpBlocked", "RequestBlocked"):
            hint = " — 유튜브가 자막 요청을 일시 차단했습니다. 잠시 후 다시 시도하세요."
        return TranscriptResult(video_id=video_id, error=f"{name}{hint}")
    except Exception as e:
        return TranscriptResult(video_id=video_id, error=f"{type(e).__name__}: {str(e)[:120]}")

    snippets = [
        Snippet(start=float(s["start"]), text=s["text"].strip())
        for s in fetched.to_raw_data()
        if s["text"].strip()
    ]
    result = TranscriptResult(
        video_id=video_id,
        snippets=snippets,
        language=fetched.language_code,
        is_generated=fetched.is_generated,
    )
    save_cache(result)
    return result


def build_context(
    video_id: str,
    title: str = "",
    description: str = "",
    top_comments: list[str] | None = None,
) -> dict:
    """AI에게 넘길 영상 맥락을 모은다.

    자막이 있으면 자막을, 없으면 제목·설명을 근거로 쓴다 (과제가 허용한 폴백).
    """
    result = fetch_transcript(video_id)
    top_comments = top_comments or []

    if result.available:
        source = "transcript"
        body = result.as_prompt_text()
    else:
        source = "title_description"
        body = f"제목: {title}\n설명: {description}".strip()

    return {
        "video_id": video_id,
        "source": source,
        "language": result.language,
        "is_generated": result.is_generated,
        "body": body,
        "top_comments": top_comments,
        "transcript_error": result.error,
        "has_timestamps": source == "transcript",
    }
