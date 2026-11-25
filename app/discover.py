"""'연애' 키워드로 뜨기 직전 영상을 유튜브 전체에서 찾는다.

기준: 조회수 1,000~5,000 · 시간당 150 이상 · 초안까지만.

  1. search.list  — 최근 N시간 안에 올라온 한국어 키워드 영상 (100유닛)
  2. videos.list  — 그 영상들의 조회수 (1유닛)
  3. feed.find_rising — 채널 RSS 와 같은 기준으로 거른다

YOUTUBE_API_KEY 가 있으면 키로, 없으면 프로필 OAuth 토큰으로 부른다.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from app.feed import Video, find_rising

API_BASE = "https://www.googleapis.com/youtube/v3/{resource}"

DEFAULT_KEYWORD = "연애"
DEFAULT_HOURS = 48      # 이보다 오래된 영상은 '뜨기 직전'이라 보기 어렵다
SEARCH_SIZE = 50        # search.list 한 번의 최대치


@dataclass
class Discovery:
    keyword: str
    hours: int
    searched: int = 0                       # 검색으로 받은 영상 수
    candidates: list[Video] = field(default_factory=list)  # 조회수를 붙인 전체
    rising: list[Video] = field(default_factory=list)      # 기준을 통과한 것
    error: str | None = None


class DiscoverError(RuntimeError):
    pass


def _parse_time(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _call(resource: str, params: dict, *, api_key: str = "", profile: str = "") -> dict:
    """같은 요청을 키 또는 OAuth 로 보낸다."""
    if api_key:
        resp = httpx.get(API_BASE.format(resource=resource),
                         params={**params, "key": api_key}, timeout=20.0)
        if resp.status_code != 200:
            reason = ""
            try:
                reason = resp.json()["error"]["errors"][0].get("reason", "")
            except Exception:
                pass
            raise DiscoverError(f"{resource} 실패: HTTP {resp.status_code} {reason}".strip())
        return resp.json()

    if not profile:
        raise DiscoverError("YOUTUBE_API_KEY 도 프로필 인증도 없습니다")
    from googleapiclient.errors import HttpError

    from app.google_auth import build_service

    service = build_service(profile)
    try:
        return getattr(service, resource)().list(**params).execute()
    except HttpError as e:
        reason = ""
        try:
            reason = e.error_details[0].get("reason", "")  # type: ignore[attr-defined]
        except Exception:
            pass
        raise DiscoverError(f"{resource} 실패: {reason or e}") from e


def to_videos(search_payload: dict, stats_payload: dict) -> list[Video]:
    """search.list + videos.list 응답을 Video 목록으로 합친다."""
    views = {
        item["id"]: int(item.get("statistics", {}).get("viewCount", 0) or 0)
        for item in stats_payload.get("items", [])
    }
    out: list[Video] = []
    for item in search_payload.get("items", []):
        vid = item.get("id", {}).get("videoId")
        sn = item.get("snippet", {})
        if not vid or vid not in views or not sn.get("publishedAt"):
            continue  # 비공개·삭제 등으로 통계가 없으면 뺀다
        thumbs = sn.get("thumbnails", {})
        thumb = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
        # search.list 의 제목·설명은 HTML 이스케이프돼 온다 (&quot; 등)
        out.append(Video(
            video_id=vid,
            title=html.unescape(sn.get("title", "")),
            channel=html.unescape(sn.get("channelTitle", "")),
            channel_id=sn.get("channelId", ""),
            published=_parse_time(sn["publishedAt"]),
            thumbnail=thumb,
            views=views[vid],
            description=html.unescape(sn.get("description", "")),
        ))
    return out


def discover_rising(
    *,
    keyword: str = DEFAULT_KEYWORD,
    hours: int = DEFAULT_HOURS,
    min_views: int = 1000,
    max_views: int = 5000,
    min_views_per_hour: float = 150.0,
    api_key: str = "",
    profile: str = "",
    now: datetime | None = None,
) -> Discovery:
    """키워드로 최근 영상을 검색해 뜨기 직전 영상을 고른다. 실패해도 예외 대신 error."""
    result = Discovery(keyword=keyword, hours=hours)
    now = now or datetime.now(timezone.utc)
    after = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        search = _call("search", {
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "order": "relevance",
            "publishedAfter": after,
            "regionCode": "KR",
            "relevanceLanguage": "ko",
            "maxResults": SEARCH_SIZE,
        }, api_key=api_key, profile=profile)
        ids = [i["id"]["videoId"] for i in search.get("items", []) if i.get("id", {}).get("videoId")]
        result.searched = len(ids)
        if not ids:
            return result
        stats = _call("videos", {"part": "statistics", "id": ",".join(ids)},
                      api_key=api_key, profile=profile)
    except DiscoverError as e:
        result.error = str(e)
        return result
    except Exception as e:
        result.error = f"{type(e).__name__}: {str(e)[:160]}"
        return result

    result.candidates = to_videos(search, stats)
    result.rising = find_rising(
        result.candidates, min_views=min_views, max_views=max_views,
        min_views_per_hour=min_views_per_hour,
    )
    return result
