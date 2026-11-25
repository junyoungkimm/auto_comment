# -*- coding: utf-8 -*-
"""댓글 게시 테스트. 실제로 유튜브에 글을 올리지 않는다 (전부 가짜 응답)."""

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app import youtube_post as YP
from app.youtube_post import PostError, PostResult, post_and_verify, post_comment, verify_comment


class FakeRequest:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error:
            raise self._error
        return self._result


class FakeCommentThreads:
    def __init__(self, insert_result=None, insert_error=None, list_result=None):
        self.insert_result = insert_result
        self.insert_error = insert_error
        self.list_result = list_result
        self.last_body = None

    def insert(self, part, body):
        self.last_body = body
        return FakeRequest(self.insert_result, self.insert_error)

    def list(self, part, id):
        return FakeRequest(self.list_result or {"items": []})


class FakeService:
    def __init__(self, threads):
        self._threads = threads

    def commentThreads(self):
        return self._threads


def install(monkeypatch, threads, channel="테스트채널"):
    monkeypatch.setattr(YP, "build_service", lambda profile: FakeService(threads))
    monkeypatch.setattr(
        YP, "whoami", lambda service: {"channel_id": "UC_me", "title": channel, "subscribers": "0"}
    )


def http_error(status, reason):
    resp = httplib2.Response({"status": status})
    err = HttpError(resp, b"{}")
    err.error_details = [{"reason": reason}]
    return err


# --- 게시 ---

def test_post_sends_correct_body(monkeypatch):
    threads = FakeCommentThreads(insert_result={"id": "Ugx123"})
    install(monkeypatch, threads)

    result = post_comment("계정1", "vid123", "댓글 본문입니다")

    assert threads.last_body == {
        "snippet": {
            "videoId": "vid123",
            "topLevelComment": {"snippet": {"textOriginal": "댓글 본문입니다"}},
        }
    }
    assert result.comment_id == "Ugx123"
    assert result.channel_title == "테스트채널"


def test_post_builds_direct_comment_url(monkeypatch):
    install(monkeypatch, FakeCommentThreads(insert_result={"id": "Ugx999"}))

    result = post_comment("계정1", "abc", "내용")

    # 이 주소를 크롬 프로필로 열면 그 댓글이 강조된다 (확인 단계). hl=ko 로 한국어 화면.
    assert result.url == "https://www.youtube.com/watch?v=abc&lc=Ugx999&hl=ko"


def test_empty_comment_is_rejected(monkeypatch):
    install(monkeypatch, FakeCommentThreads())
    with pytest.raises(PostError, match="빈 댓글"):
        post_comment("계정1", "vid", "   ")


def test_missing_comment_id_is_an_error(monkeypatch):
    install(monkeypatch, FakeCommentThreads(insert_result={}))
    with pytest.raises(PostError, match="댓글 ID"):
        post_comment("계정1", "vid", "내용")


# --- 오류를 사람 말로 ---

@pytest.mark.parametrize(
    "reason,expected",
    [
        ("commentsDisabled", "댓글이 꺼져"),
        ("quotaExceeded", "할당량"),
        ("rateLimitExceeded", "너무 빠릅니다"),
        ("videoNotFound", "찾을 수 없습니다"),
        ("ineligibleAccount", "유튜브 채널이 있는지"),
    ],
)
def test_known_errors_are_explained_in_korean(monkeypatch, reason, expected):
    install(monkeypatch, FakeCommentThreads(insert_error=http_error(403, reason)))

    with pytest.raises(PostError, match=expected):
        post_comment("계정1", "vid", "내용")


def test_expired_auth_tells_user_how_to_fix(monkeypatch):
    install(monkeypatch, FakeCommentThreads(insert_error=http_error(401, "")))

    with pytest.raises(PostError, match="auth_youtube"):
        post_comment("계정1", "vid", "내용")


# --- 확인 ---

def test_verify_true_when_comment_is_found(monkeypatch):
    install(monkeypatch, FakeCommentThreads(list_result={"items": [{"id": "Ugx1"}]}))
    assert verify_comment("계정1", "Ugx1") is True


def test_verify_false_when_not_found(monkeypatch):
    install(monkeypatch, FakeCommentThreads(list_result={"items": []}))
    assert verify_comment("계정1", "Ugx1") is False


def test_post_and_verify_sets_flag(monkeypatch):
    threads = FakeCommentThreads(
        insert_result={"id": "Ugx1"}, list_result={"items": [{"id": "Ugx1"}]}
    )
    install(monkeypatch, threads)

    result = post_and_verify("계정1", "vid", "내용")

    assert result.verified is True


def test_post_and_verify_reports_unverified(monkeypatch):
    threads = FakeCommentThreads(insert_result={"id": "Ugx1"}, list_result={"items": []})
    install(monkeypatch, threads)

    assert post_and_verify("계정1", "vid", "내용").verified is False
