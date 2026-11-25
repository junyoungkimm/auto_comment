# -*- coding: utf-8 -*-
"""인기 댓글 가져오기 테스트. 실제 API 를 부르지 않는다."""

from app import comments as C


def thread(text, likes, author="UC_other"):
    return {
        "snippet": {
            "topLevelComment": {
                "snippet": {
                    "textOriginal": text,
                    "likeCount": likes,
                    "authorChannelId": {"value": author},
                }
            }
        }
    }


def test_parse_sorts_by_likes_and_keeps_top():
    payload = {"items": [thread(f"댓글{i}", i) for i in range(15)]}
    out = C.parse_threads(payload)
    assert len(out) == C.KEEP_COUNT
    assert out[0].text == "댓글14" and out[0].likes == 14


def test_parse_skips_empty_and_own_and_trims_long():
    payload = {"items": [
        thread("", 100),
        thread("내 댓글", 50, author="UC_me"),
        thread("가" * 300, 10),
        thread("줄\n바꿈   공백", 5),
    ]}
    out = C.parse_threads(payload, exclude_channel_id="UC_me")
    assert [c.likes for c in out] == [10, 5]
    assert len(out[0].text) == C.MAX_COMMENT_CHARS + 1 and out[0].text.endswith("…")
    assert out[1].text == "줄 바꿈 공백"


def test_no_credentials_returns_reason():
    r = C.fetch_top_comments("vid00000001", use_cache=False)
    assert r.items == [] and "없습니다" in r.error


class FakeResp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


def test_api_key_path(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout):
        seen.update(params)
        return FakeResp(200, {"items": [thread("공감해요", 3)]})

    monkeypatch.setattr(C.httpx, "get", fake_get)
    r = C.fetch_top_comments("vid00000002", api_key="K", use_cache=False)
    assert r.texts == ["공감해요"] and r.error is None
    assert seen["order"] == "relevance" and seen["key"] == "K"


def test_comments_disabled_is_explained(monkeypatch):
    body = {"error": {"errors": [{"reason": "commentsDisabled"}]}}
    monkeypatch.setattr(C.httpx, "get", lambda *a, **k: FakeResp(403, body))
    r = C.fetch_top_comments("vid00000003", api_key="K", use_cache=False)
    assert r.items == [] and r.error == "댓글이 꺼진 영상입니다"


def test_failure_is_not_cached(monkeypatch):
    monkeypatch.setattr(C, "_cache", {})
    monkeypatch.setattr(C.httpx, "get", lambda *a, **k: FakeResp(500, {}))
    C.fetch_top_comments("vid00000004", api_key="K")
    assert "vid00000004" not in C._cache
