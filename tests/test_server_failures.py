# -*- coding: utf-8 -*-
"""게시 실패 시 이유 · 화면 캡처가 기록되는지. 실제 게시·캡처는 하지 않는다."""

import pytest
from fastapi.testclient import TestClient

from app import server as S
from app.capture import screenshot_name
from app.profiles import ProfileStatus
from app.storage import ActivityLog
from app.youtube_post import PostError

GOOD = "3:12에 연락 기다리는 마음 얘기 너무 공감돼요. 운명원 연애사주가 잘 본다던데 저도 한번 보고 싶네요. (광고)"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "activity", ActivityLog(tmp_path / "log.jsonl"))
    # 이 컴퓨터의 실제 프로필·토큰 유무와 무관하게 돌도록 계정 상태를 고정한다
    monkeypatch.setattr(S, "_statuses", lambda: [
        ProfileStatus(n, has_browser=True, has_token=True) for n in ("계정1", "계정2", "계정3")
    ])
    monkeypatch.setattr(S, "capture_screen", lambda out_dir, vid: f"fail-{vid}.png")
    return TestClient(S.app)


def post(client, video_id="vid00000001"):
    return client.post("/api/post", json={
        "video_id": video_id, "video_title": "제목", "profile": "계정1", "text": GOOD,
    })


def test_post_error_records_reason_and_capture(client, monkeypatch):
    def boom(*a):
        raise PostError("이 영상은 댓글이 꺼져 있습니다.")

    monkeypatch.setattr(S, "post_and_verify", boom)
    r = post(client)
    assert r.status_code == 502

    rec = S.activity.all()[-1]
    assert rec.status == "failed"
    assert rec.error == "이 영상은 댓글이 꺼져 있습니다."
    assert rec.screenshot == "fail-vid00000001.png"

    log = client.get("/api/log").json()["records"][0]
    assert log["screenshot"] == "/api/screenshots/fail-vid00000001.png"


def test_auth_error_is_recorded_not_500(client, monkeypatch):
    class RefreshError(Exception):
        pass

    def boom(*a):
        raise RefreshError("invalid_grant")

    monkeypatch.setattr(S, "post_and_verify", boom)
    r = post(client)
    assert r.status_code == 502
    assert "인증이 만료" in r.json()["detail"]
    assert S.activity.all()[-1].status == "failed"


def test_rule_block_is_not_a_failure(client):
    """규칙에 막힌 건 게시 시도가 아니므로 실패 기록·캡처를 남기지 않는다."""
    r = client.post("/api/post", json={"video_id": "vid00000001", "text": "짧음"})
    assert r.status_code == 400
    assert S.activity.all() == []


def test_screenshot_route_blocks_traversal(client):
    assert client.get("/api/screenshots/..%2F..%2F.env").status_code == 404


def test_screenshot_name_is_safe():
    name = screenshot_name("../../evil")
    assert "/" not in name and ".." not in name and name.endswith(".png")


# --- 브라우저 타이핑 게시 ---

import time as _time

from app.browser_post import TypingPostError, TypingResult


def _wait_job(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        _time.sleep(0.02)
    raise AssertionError("job did not finish")


def _typing(client, video_id="vid00000009"):
    r = client.post("/api/post-typing", json={
        "video_id": video_id, "video_title": "제목", "profile": "계정1", "text": GOOD,
    })
    assert r.status_code == 200, r.text
    return _wait_job(client, r.json()["job_id"])


def test_typing_success_records_posted(client, monkeypatch):
    steps = []

    def fake(profile_dir, video_id, text, **kw):
        for s in ("open", "typing", "submit", "verify"):
            kw["on_step"](s)
            steps.append(s)
        return TypingResult(video_id=video_id, comment_id="Ugx1", seen_on_page=True)

    monkeypatch.setattr(S, "post_by_typing", fake)
    monkeypatch.setattr(S, "_lookup_by_api", lambda *a: "Ugx1")
    job = _typing(client)
    assert job["status"] == "done"
    assert job["result"]["verified"] and job["result"]["verified_by_api"]
    assert "lc=Ugx1" in job["result"]["comment_url"]
    rec = S.activity.all()[-1]
    assert rec.status == "posted" and rec.method == "typing"
    assert steps == ["open", "typing", "submit", "verify"]


def test_typing_fail_before_submit_is_failure_with_browser_capture(client, monkeypatch):
    def fake(*a, **kw):
        raise TypingPostError("댓글 입력창을 찾지 못했습니다", screenshot="b.png", submitted=False)

    monkeypatch.setattr(S, "post_by_typing", fake)
    job = _typing(client)
    assert job["status"] == "failed" and "입력창" in job["error"]
    rec = S.activity.all()[-1]
    assert rec.status == "failed" and rec.screenshot == "b.png"  # 브라우저 캡처를 그대로 쓴다


def test_typing_submitted_but_unseen_is_rescued_by_api(client, monkeypatch):
    """게시 버튼은 눌렀는데 화면 확인이 실패 → API 로 찾으면 '게시'로 기록 (영상당 1개 보호)."""
    def fake(*a, **kw):
        raise TypingPostError("화면에서 못 찾음", screenshot="c.png", submitted=True)

    monkeypatch.setattr(S, "post_by_typing", fake)
    monkeypatch.setattr(S, "_lookup_by_api", lambda *a: "Ugx2")
    job = _typing(client)
    assert job["status"] == "done" and job["result"]["seen_on_page"] is False
    assert S.activity.all()[-1].status == "posted"
    # 같은 영상에 다시 달 수 없다
    again = client.post("/api/post-typing", json={"video_id": "vid00000009", "text": GOOD})
    assert again.status_code == 409


def test_typing_lock_released_after_failure(client, monkeypatch):
    monkeypatch.setattr(S, "post_by_typing",
                        lambda *a, **kw: (_ for _ in ()).throw(TypingPostError("x")))
    _typing(client, "vid0000000a")
    _typing(client, "vid0000000b")  # 잠금이 풀려 있어야 두 번째도 시작된다


def test_typing_seen_on_page_but_not_public_is_not_verified(client, monkeypatch, tmp_path):
    """작성자 화면에만 보이고 API 로 안 잡히면 '확인됨'이 아니다 (유튜브가 숨긴 경우)."""
    token = tmp_path / "token.json"
    token.write_text("{}")
    monkeypatch.setattr(S, "token_path", lambda p: token)
    monkeypatch.setattr(S, "post_by_typing", lambda *a, **kw: TypingResult(
        video_id="vid0000000c", comment_id="UgxH", seen_on_page=True))
    monkeypatch.setattr(S, "_lookup_by_api", lambda *a: "")
    job = _typing(client, "vid0000000c")
    assert job["status"] == "done"
    assert job["result"]["verified"] is False
    assert "공개 댓글로 조회되지 않습니다" in job["result"]["warnings"][-1]


def test_placeholder_draft_cannot_be_posted(client):
    generic = "영상 내용 공감되네요. 저도 비슷한 고민이라 운명원 연애사주 한번 보고 싶어지네요. (광고)"
    for path in ("/api/post", "/api/post-typing"):
        r = client.post(path, json={"video_id": "vid0000000d", "text": generic})
        assert r.status_code == 400 and "임시 문구" in r.json()["detail"]
    v = client.post("/api/validate", json={"text": generic}).json()
    assert v["ok"] is False and any("임시 문구" in e for e in v["errors"])
    assert S.activity.all() == []   # 막힌 건 실패 기록도 아니다


def test_launch_error_when_profile_window_already_open_is_readable():
    """녹화 중 실제로 뜬 오류 — 기술 문구 대신 사람이 할 일을 알려준다."""
    from app.browser_post import _explain_launch_error

    class TargetClosedError(Exception):
        pass

    raw = TargetClosedError("BrowserType.launch_persistent_context: Target page, context or browser has been closed")
    assert _explain_launch_error(raw) == "이 계정의 크롬 창이 이미 열려 있습니다. 그 창을 닫고 다시 시도하세요."
    assert "열지 못했습니다" in _explain_launch_error(RuntimeError("chrome not found"))
