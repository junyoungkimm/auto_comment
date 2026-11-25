"""유튜브 공식 RSS 피드로 영상 목록을 가져온다.

API 키가 필요 없다. 채널당 최신 15개를 돌려주며, 조회수가 포함되어 있어
'시간당 조회수'를 계산할 수 있다 (가점 항목: 뜨기 직전 영상 찾기).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
OEMBED_URL = "https://www.youtube.com/oembed?url={watch_url}&format=json"

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
VIDEO_ID_RE = re.compile(r"[\w-]{11}")


@dataclass(frozen=True)
class Video:
    video_id: str
    title: str
    channel: str
    channel_id: str
    published: datetime
    thumbnail: str
    views: int
    description: str = ""

    @property
    def url(self) -> str:
        return WATCH_URL.format(video_id=self.video_id)

    @property
    def age_hours(self) -> float:
        delta = datetime.now(timezone.utc) - self.published
        return max(delta.total_seconds() / 3600, 1 / 60)  # 0으로 나누지 않게

    @property
    def views_per_hour(self) -> float:
        return self.views / self.age_hours


def parse_feed(xml_text: str) -> list[Video]:
    """RSS XML 한 개를 Video 목록으로 바꾼다."""
    root = ET.fromstring(xml_text)
    channel_title = root.findtext("a:title", default="", namespaces=NS)
    channel_id = root.findtext("yt:channelId", default="", namespaces=NS)

    videos: list[Video] = []
    for entry in root.findall("a:entry", NS):
        group = entry.find("media:group", NS)
        if group is None:
            continue
        video_id = entry.findtext("yt:videoId", default="", namespaces=NS)
        published_raw = entry.findtext("a:published", default="", namespaces=NS)
        if not video_id or not published_raw:
            continue

        thumb_el = group.find("media:thumbnail", NS)
        stats_el = group.find("media:community/media:statistics", NS)
        author = entry.find("a:author", NS)

        videos.append(
            Video(
                video_id=video_id,
                title=entry.findtext("a:title", default="", namespaces=NS),
                channel=(
                    author.findtext("a:name", default="", namespaces=NS)
                    if author is not None
                    else channel_title
                ),
                channel_id=channel_id,
                published=datetime.fromisoformat(published_raw),
                thumbnail=thumb_el.get("url", "") if thumb_el is not None else "",
                views=int(stats_el.get("views", 0)) if stats_el is not None else 0,
                description=group.findtext("media:description", default="", namespaces=NS) or "",
            )
        )
    return videos


def fetch_channel(channel_id: str, client: httpx.Client | None = None) -> list[Video]:
    """채널 하나의 최신 영상을 가져온다."""
    owned = client is None
    client = client or httpx.Client(timeout=20.0, follow_redirects=True)
    try:
        resp = client.get(FEED_URL.format(channel_id=channel_id))
        resp.raise_for_status()
        return parse_feed(resp.text)
    finally:
        if owned:
            client.close()


def fetch_channels(channel_ids: list[str]) -> tuple[list[Video], list[tuple[str, str]]]:
    """여러 채널을 모아 최신순으로 정렬한다.

    돌려주는 값: (영상 목록, [(채널ID, 실패 사유)])
    """
    videos: list[Video] = []
    errors: list[tuple[str, str]] = []
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for cid in channel_ids:
            try:
                videos.extend(fetch_channel(cid, client))
            except Exception as e:  # 한 채널이 실패해도 나머지는 살린다
                errors.append((cid, f"{type(e).__name__}: {e}"))
    videos.sort(key=lambda v: v.published, reverse=True)
    return videos, errors


def find_rising(
    videos: list[Video],
    min_views: int = 1000,
    max_views: int = 5000,
    min_views_per_hour: float = 150.0,
) -> list[Video]:
    """뜨기 직전 영상을 고른다 (가점 항목).

    과제 기준: 조회수 1,000~5,000 · 시간당 150 이상.
    """
    hits = [
        v
        for v in videos
        if min_views <= v.views <= max_views and v.views_per_hour >= min_views_per_hour
    ]
    hits.sort(key=lambda v: v.views_per_hour, reverse=True)
    return hits


def fetch_oembed(video_id: str, client: httpx.Client | None = None) -> dict:
    """유튜브 공식 oEmbed 로 제목·채널·썸네일을 가져온다.

    RSS 에 없는 영상(링크 직접 입력)의 메타데이터를 채우는 용도.
    API 키가 필요 없다.
    """
    owned = client is None
    client = client or httpx.Client(timeout=15.0, follow_redirects=True)
    try:
        resp = client.get(OEMBED_URL.format(watch_url=WATCH_URL.format(video_id=video_id)))
        resp.raise_for_status()
        data = resp.json()
        return {
            "title": data.get("title", ""),
            "channel": data.get("author_name", ""),
            "thumbnail": data.get("thumbnail_url", ""),
        }
    except Exception:
        # 비공개·삭제된 영상이면 oEmbed 가 404 를 준다. 호출부에서 기본값을 쓴다.
        return {}
    finally:
        if owned:
            client.close()


def resolve_channel_id(handle_or_url: str, client: httpx.Client | None = None) -> str:
    """@핸들 또는 채널 URL에서 channel_id(UC...)를 찾아낸다."""
    value = handle_or_url.strip()
    if CHANNEL_ID_RE.match(value):
        return value

    if value.startswith("@"):
        url = f"https://www.youtube.com/{value}"
    elif value.startswith("http"):
        url = value
    else:
        url = f"https://www.youtube.com/@{value}"

    owned = client is None
    client = client or httpx.Client(timeout=20.0, follow_redirects=True)
    try:
        resp = client.get(url, headers={"Accept-Language": "ko-KR"})
        resp.raise_for_status()
        m = re.search(r'"(?:channelId|externalChannelId)"\s*:\s*"(UC[\w-]{22})"', resp.text)
        if not m:
            m = re.search(r"channel/(UC[\w-]{22})", resp.text)
        if not m:
            raise ValueError(f"채널 ID를 찾지 못했습니다: {handle_or_url}")
        return m.group(1)
    finally:
        if owned:
            client.close()


def extract_video_id(url_or_id: str) -> str:
    """영상 URL 또는 ID에서 11자리 video_id를 뽑는다 (가점: 링크 직접 입력)."""
    value = url_or_id.strip()
    patterns = [
        r"[?&]v=([\w-]{11})",
        r"youtu\.be/([\w-]{11})",
        r"/shorts/([\w-]{11})",
        r"/embed/([\w-]{11})",
        r"/live/([\w-]{11})",
    ]
    for pat in patterns:
        m = re.search(pat, value)
        if m:
            return m.group(1)
    if re.fullmatch(r"[\w-]{11}", value):
        return value
    raise ValueError(f"영상 ID를 찾을 수 없습니다: {url_or_id}")
