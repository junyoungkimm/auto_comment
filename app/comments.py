"""영상의 인기 댓글을 가져온다.

과제 요구: "AI가 자막(없으면 제목·설명)과 인기 댓글을 읽고".

YouTube Data API 의 commentThreads.list(order=relevance) 를 쓴다 (약 1유닛).
YOUTUBE_API_KEY 가 있으면 키로, 없으면 이미 받아둔 프로필 OAuth 토큰으로 부른다.
실패해도 예외를 던지지 않는다 — 인기 댓글은 보조 자료라 없어도 분석은 돌아야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"

FETCH_COUNT = 20      # 이만큼 받아서
KEEP_COUNT = 10       # 좋아요 순으로 이만큼 남긴다
MAX_COMMENT_CHARS = 150  # 긴 댓글은 잘라서 프롬프트를 아낀다


@dataclass(frozen=True)
class TopComment:
    text: str
    likes: int


@dataclass
class TopComments:
    video_id: str
    items: list[TopComment] = field(default_factory=list)
    error: str | None = None

    @property
    def texts(self) -> list[str]:
        return [c.text for c in self.items]


def _clean(text: str) -> str:
    text = " ".join((text or "").split())
    if len(text) > MAX_COMMENT_CHARS:
        text = text[:MAX_COMMENT_CHARS].rstrip() + "…"
    return text


def parse_threads(payload: dict, exclude_channel_id: str = "") -> list[TopComment]:
    """commentThreads.list 응답을 TopComment 목록으로 바꾼다 (좋아요 많은 순)."""
    out: list[TopComment] = []
    for item in payload.get("items", []):
        snippet = (
            item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
        )
        author = snippet.get("authorChannelId", {}).get("value", "")
        if exclude_channel_id and author == exclude_channel_id:
            continue  # 내가 단 댓글은 '시청자 반응'이 아니다
        text = _clean(snippet.get("textOriginal") or snippet.get("textDisplay", ""))
        if not text:
            continue
        out.append(TopComment(text=text, likes=int(snippet.get("likeCount", 0) or 0)))
    out.sort(key=lambda c: c.likes, reverse=True)
    return out[:KEEP_COUNT]


def _explain(status: int, reason: str) -> str:
    known = {
        "commentsDisabled": "댓글이 꺼진 영상입니다",
        "videoNotFound": "영상을 찾을 수 없습니다",
        "quotaExceeded": "API 할당량을 모두 썼습니다",
        "forbidden": "댓글을 읽을 권한이 없습니다",
    }
    return known.get(reason, f"HTTP {status} {reason}".strip())


def _params(video_id: str) -> dict:
    return {
        "part": "snippet",
        "videoId": video_id,
        "order": "relevance",
        "maxResults": FETCH_COUNT,
        "textFormat": "plainText",
    }


def _fetch_with_key(video_id: str, api_key: str) -> dict:
    resp = httpx.get(API_URL, params={**_params(video_id), "key": api_key}, timeout=15.0)
    if resp.status_code != 200:
        reason = ""
        try:
            reason = resp.json()["error"]["errors"][0].get("reason", "")
        except Exception:
            pass
        raise RuntimeError(_explain(resp.status_code, reason))
    return resp.json()


def _fetch_with_oauth(video_id: str, profile: str) -> dict:
    from googleapiclient.errors import HttpError

    from app.google_auth import build_service

    service = build_service(profile)
    try:
        return service.commentThreads().list(**_params(video_id)).execute()
    except HttpError as e:
        reason = ""
        try:
            reason = e.error_details[0].get("reason", "")  # type: ignore[attr-defined]
        except Exception:
            pass
        raise RuntimeError(_explain(getattr(e.resp, "status", 0), reason)) from e


_cache: dict[str, TopComments] = {}


def fetch_top_comments(
    video_id: str, *, api_key: str = "", profile: str = "", use_cache: bool = True
) -> TopComments:
    """인기 댓글을 가져온다. 키도 토큰도 없으면 빈 결과와 사유를 돌려준다."""
    if use_cache and video_id in _cache:
        return _cache[video_id]

    if not api_key and not profile:
        return TopComments(video_id, error="YOUTUBE_API_KEY 도 프로필 인증도 없습니다")

    try:
        payload = (
            _fetch_with_key(video_id, api_key)
            if api_key
            else _fetch_with_oauth(video_id, profile)
        )
    except Exception as e:
        return TopComments(video_id, error=str(e)[:160] or type(e).__name__)

    result = TopComments(video_id, items=parse_threads(payload))
    _cache[video_id] = result  # 성공한 것만 캐시 (실패는 다음에 재시도)
    return result
