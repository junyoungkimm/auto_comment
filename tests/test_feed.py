# -*- coding: utf-8 -*-
"""RSS 파싱과 필터 규칙 테스트. 네트워크를 쓰지 않는다."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.feed import Video, extract_video_id, find_rising, parse_feed

FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


def make_video(video_id="abc12345678", views=2000, age_hours=10.0) -> Video:
    return Video(
        video_id=video_id,
        title="제목",
        channel="채널",
        channel_id="UC" + "x" * 22,
        published=datetime.now(timezone.utc) - timedelta(hours=age_hours),
        thumbnail="https://i3.ytimg.com/vi/x/hqdefault.jpg",
        views=views,
    )


# --- 파싱 ---

def test_parse_feed_extracts_required_fields():
    videos = parse_feed(FIXTURE.read_text(encoding="utf-8"))

    assert len(videos) == 15  # 유튜브 RSS는 채널당 최신 15개
    v = videos[0]
    # 영상 목록에 필요한 네 가지가 모두 있어야 한다
    assert v.title
    assert v.channel
    assert v.thumbnail.startswith("https://")
    assert isinstance(v.published, datetime)
    assert v.published.tzinfo is not None
    assert len(v.video_id) == 11
    assert v.views > 0


def test_parse_feed_builds_watch_url():
    v = parse_feed(FIXTURE.read_text(encoding="utf-8"))[0]
    assert v.url == f"https://www.youtube.com/watch?v={v.video_id}"


def test_parse_feed_on_empty_feed():
    empty = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    assert parse_feed(empty) == []


# --- 시간당 조회수 ---

def test_views_per_hour():
    v = make_video(views=1500, age_hours=10.0)
    assert v.views_per_hour == pytest.approx(150.0, rel=0.02)


def test_views_per_hour_does_not_divide_by_zero():
    v = make_video(views=100, age_hours=0.0)
    assert v.views_per_hour > 0  # 방금 올라온 영상


# --- 뜨기 직전 영상 ---

def test_find_rising_applies_both_conditions():
    videos = [
        make_video("in__range__", views=3000, age_hours=10),   # 300/h  -> 통과
        make_video("too__few___", views=500, age_hours=1),     # 조회수 미달
        make_video("too__many__", views=90000, age_hours=10),  # 조회수 초과
        make_video("too__slow__", views=3000, age_hours=100),  # 30/h  -> 속도 미달
    ]

    hits = find_rising(videos)

    assert [v.video_id for v in hits] == ["in__range__"]


def test_find_rising_sorts_by_speed():
    videos = [
        make_video("slower_____", views=2000, age_hours=10),  # 200/h
        make_video("faster_____", views=4000, age_hours=10),  # 400/h
    ]

    hits = find_rising(videos)

    assert [v.video_id for v in hits] == ["faster_____", "slower_____"]


def test_find_rising_boundaries_are_inclusive():
    """기준이 '1,000 ~ 5,000 · 시간당 150 이상' 이므로 경계를 포함한다."""
    exact = make_video(views=1500, age_hours=10)  # 1500뷰, 150/h
    assert find_rising([exact]) == [exact]


# --- 링크 직접 입력 ---

@pytest.mark.parametrize(
    "value",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=30s",
        "dQw4w9WgXcQ",
        "  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ",
    ],
)
def test_extract_video_id_accepts_common_forms(value):
    assert extract_video_id(value) == "dQw4w9WgXcQ"


def test_extract_video_id_rejects_garbage():
    with pytest.raises(ValueError, match="영상 ID"):
        extract_video_id("https://example.com/hello")
