# -*- coding: utf-8 -*-
"""계정 배정 (계정1~3 중 고르기 또는 영상마다 돌아가며 자동 배정)."""

import pytest
from fastapi.testclient import TestClient

from app import server as S
from app.profiles import ProfileStatus, next_profile, profile_status
from app.storage import ActivityLog, Record

ALL = [ProfileStatus(n, True, True) for n in ("계정1", "계정2", "계정3")]


def test_rotates_after_last_posted():
    assert next_profile(ALL, [], "typing") == "계정1"
    assert next_profile(ALL, ["계정1"], "typing") == "계정2"
    assert next_profile(ALL, ["계정1", "계정2"], "typing") == "계정3"
    assert next_profile(ALL, ["계정1", "계정2", "계정3"], "typing") == "계정1"


def test_skips_accounts_not_ready_for_method():
    st = [ProfileStatus("계정1", True, True), ProfileStatus("계정2", True, False),
          ProfileStatus("계정3", False, False)]
    assert next_profile(st, ["계정1"], "typing") == "계정2"   # 브라우저만 있으면 입력 게시 가능
    assert next_profile(st, ["계정1"], "api") == "계정1"      # 토큰은 계정1 뿐
    assert next_profile([ProfileStatus("계정1", False, False)], [], "typing") is None


def test_unknown_last_profile_starts_from_first():
    """이름을 바꾸기 전 기록(유튜브1)이 남아 있어도 첫 계정부터."""
    assert next_profile(ALL, ["유튜브1"], "typing") == "계정1"


def test_profile_status_reads_folders(tmp_path):
    (tmp_path / "계정1" / "Default").mkdir(parents=True)
    (tmp_path / "계정2").mkdir()   # 폴더만 있고 크롬이 한 번도 안 열림
    tok = tmp_path / "token_계정1.json"
    tok.write_text("{}")
    st = profile_status(["계정1", "계정2"], tmp_path, lambda n: tmp_path / f"token_{n}.json")
    assert [(x.has_browser, x.has_token) for x in st] == [(True, True), (False, False)]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "activity", ActivityLog(tmp_path / "log.jsonl"))
    monkeypatch.setattr(S, "_statuses", lambda: [
        ProfileStatus("계정1", True, True), ProfileStatus("계정2", True, False),
        ProfileStatus("계정3", False, False),
    ])
    return TestClient(S.app)


def test_state_reports_accounts_and_next(client):
    S.activity.append(Record("v1", "t", "계정1", "c", "posted"))
    st = client.get("/api/state").json()
    assert [p["name"] for p in st["profiles"]] == ["계정1", "계정2", "계정3"]
    assert st["next_profile"] == {"typing": "계정2", "api": "계정1"}


def test_choosing_unready_account_is_refused(client):
    text = "3:12에 연락 기다리는 마음 얘기 너무 공감돼요. 운명원 연애사주가 잘 본다던데 저도 한번 보고 싶네요. (광고)"
    r = client.post("/api/post-typing", json={"video_id": "vid00000001", "profile": "계정3", "text": text})
    assert r.status_code == 409 and "setup_profile.py 계정3" in r.json()["detail"]
    r = client.post("/api/post", json={"video_id": "vid00000001", "profile": "계정2", "text": text})
    assert r.status_code == 409 and "auth_youtube.py 계정2" in r.json()["detail"]
