# -*- coding: utf-8 -*-
"""'연애' 키워드로 뜨기 직전 영상 찾기. 실제 API 를 부르지 않는다."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import discover as D
from app import server as S
from app.profiles import ProfileStatus
from app.storage import ActivityLog

NOW = datetime.now(timezone.utc)


def search_item(vid, title, hours_ago):
    return {
        "id": {"videoId": vid},
        "snippet": {
            "title": title,
            "channelTitle": "채널 &amp; 이름",
            "channelId": "UCx",
            "publishedAt": (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "description": "",
            "thumbnails": {"high": {"url": f"https://i.ytimg.com/{vid}.jpg"}},
        },
    }


SEARCH = {"items": [
    search_item("aaaaaaaaaaa", "&quot;썸&quot; 타는 중 연애", 10),   # 2,000 / 10h = 200/h → 통과
    search_item("bbbbbbbbbbb", "이미 뜬 연애 영상", 5),             # 90,000 → 상한 초과
    search_item("ccccccccccc", "느린 연애 영상", 40),               # 2,000 / 40h = 50/h → 속도 미달
    search_item("ddddddddddd", "통계 없는 영상", 3),                # videos.list 에 없음 → 제외
]}
STATS = {"items": [
    {"id": "aaaaaaaaaaa", "statistics": {"viewCount": "2000"}},
    {"id": "bbbbbbbbbbb", "statistics": {"viewCount": "90000"}},
    {"id": "ccccccccccc", "statistics": {"viewCount": "2000"}},
]}


def fake_call(resource, params, **kw):
    return SEARCH if resource == "search" else STATS


def test_to_videos_unescapes_and_drops_missing_stats():
    vids = D.to_videos(SEARCH, STATS)
    assert [v.video_id for v in vids] == ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
    assert vids[0].title == '"썸" 타는 중 연애'
    assert vids[0].channel == "채널 & 이름"


def test_discover_applies_assignment_criteria(monkeypatch):
    seen = {}

    def spy(resource, params, **kw):
        seen.setdefault(resource, params)
        return fake_call(resource, params)

    monkeypatch.setattr(D, "_call", spy)
    d = D.discover_rising(profile="계정1")
    assert d.error is None and d.searched == 4
    assert [v.video_id for v in d.rising] == ["aaaaaaaaaaa"]
    assert seen["search"]["q"] == "연애" and seen["search"]["regionCode"] == "KR"
    assert seen["search"]["publishedAfter"].endswith("Z")


def test_discover_reports_error_instead_of_raising(monkeypatch):
    def boom(*a, **kw):
        raise D.DiscoverError("search 실패: quotaExceeded")

    monkeypatch.setattr(D, "_call", boom)
    d = D.discover_rising(profile="계정1")
    assert d.rising == [] and "quotaExceeded" in d.error


def test_no_credentials():
    d = D.discover_rising()
    assert d.error and "없습니다" in d.error


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "activity", ActivityLog(tmp_path / "log.jsonl"))
    # 이 컴퓨터의 실제 프로필·토큰 유무와 무관하게 돌도록 계정 상태를 고정한다
    monkeypatch.setattr(S, "_statuses", lambda: [
        ProfileStatus(n, has_browser=True, has_token=True) for n in ("계정1", "계정2", "계정3")
    ])
    monkeypatch.setattr(S, "_draft_only", set())
    monkeypatch.setattr(S, "_videos", {})
    monkeypatch.setattr(D, "_call", fake_call)
    return TestClient(S.app)


def test_endpoint_marks_draft_only_and_blocks_posting(client):
    r = client.post("/api/videos/rising").json()
    assert [v["video_id"] for v in r["videos"]] == ["aaaaaaaaaaa"]
    assert r["videos"][0]["draft_only"] is True and r["videos"][0]["rising"] is True

    text = "3:12에 연락 기다리는 마음 얘기 너무 공감돼요. 운명원 연애사주가 잘 본다던데 저도 한번 보고 싶네요. (광고)"
    for path in ("/api/post", "/api/post-typing"):
        blocked = client.post(path, json={"video_id": "aaaaaaaaaaa", "text": text})
        assert blocked.status_code == 409 and "초안까지만" in blocked.json()["detail"]
