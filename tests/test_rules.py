# -*- coding: utf-8 -*-
"""운영 규칙 테스트."""

import pytest

from app.rules import PostingGate, validate_comment

# 규칙을 모두 지키는 기본 댓글 (광고 표기 포함, 40~120자)
GOOD = (
    "영상에서 읽씹이 답이라고 한 부분 공감되네요. 저도 비슷한 고민이라 "
    "운명원 연애사주 한번 보려고요. (광고)"
)


def v(text, **kw):
    return validate_comment(text, **kw)


# --- 길이 ---

def test_valid_comment_passes():
    assert v(GOOD).ok, v(GOOD).errors


def test_too_short_is_rejected():
    r = v("짧다 (광고) 운명원")
    assert not r.ok
    assert any("길이 미달" in e for e in r.errors)


def test_too_long_is_rejected():
    r = v("가" * 121 + " 운명원 광고")
    assert not r.ok
    assert any("길이 초과" in e for e in r.errors)


def test_length_boundaries_are_inclusive():
    exact_40 = "운명원 광고 " + "가" * 33   # 정확히 40자
    assert len(exact_40) == 40
    assert v(exact_40).ok


# --- 금지 항목 ---

@pytest.mark.parametrize(
    "bad",
    [
        "영상 잘 봤어요 https://unmyeongwon.com 에서 보세요 운명원 광고입니다 진짜로요",
        "영상 잘 봤어요 www.example.com 참고하세요 운명원 광고입니다 진짜로 좋아요",
        "영상 잘 봤어요 unmyeongwon.co.kr 확인해보세요 운명원 광고입니다 좋아요",
    ],
)
def test_links_are_rejected(bad):
    r = v(bad)
    assert not r.ok
    assert any("링크" in e for e in r.errors)


def test_hashtags_are_rejected():
    r = v("영상 잘 봤습니다 공감되네요 운명원 연애사주 궁금해지네요 광고 #연애사주 #운명원")
    assert not r.ok
    assert any("해시태그" in e for e in r.errors)


@pytest.mark.parametrize(
    "bad",
    [
        "영상 공감되네요 저는 운명원 가봤는데 진짜 잘 보시더라고요 광고예요 추천합니다",
        "영상 공감되네요 운명원 후기 남기자면 정말 잘 맞췄습니다 광고 글이에요 추천",
        "영상 공감되네요 운명원 다녀왔는데 소름돋게 맞추셨어요 광고입니다 추천드려요",
    ],
)
def test_fabricated_experience_is_rejected(bad):
    r = v(bad)
    assert not r.ok
    assert any("직접 이용해 본 것처럼" in e for e in r.errors)


def test_mentioning_brand_without_claiming_use_is_allowed():
    """'잘 본다던데 / 보고 싶다' 같은 전언·희망은 후기가 아니다."""
    text = (
        "영상에서 말한 밀당 얘기 공감돼요. 운명원 연애사주가 잘 본다던데 "
        "저도 한번 보고 싶네요. (광고)"
    )
    r = v(text)
    assert r.ok, r.errors


# --- 광고 표기 (이 프로젝트의 추가 규칙) ---

def test_missing_disclosure_is_rejected_by_default():
    text = "영상에서 읽씹 얘기 나온 부분 공감되네요 운명원 연애사주 한번 보고 싶어지네요"
    r = v(text)
    assert not r.ok
    assert any("광고 표기" in e for e in r.errors)


def test_disclosure_can_be_turned_off():
    text = "영상에서 읽씹 얘기 나온 부분 공감되네요 운명원 연애사주 한번 보고 싶어지네요"
    assert v(text, require_disclosure=False).ok


def test_missing_brand_is_a_warning_not_an_error():
    text = "영상에서 읽씹 얘기 나온 부분 정말 공감되네요 저도 비슷한 고민이 많습니다 (광고)"
    r = v(text)
    assert r.ok
    assert any("운명원" in w for w in r.warnings)


# --- 게시 제한 ---

def test_same_video_twice_is_blocked():
    gate = PostingGate(daily_max=10, posted_today=1, posted_video_ids=frozenset({"vid1"}))
    assert not gate.check("vid1").ok
    assert gate.check("vid2").ok


def test_daily_limit_is_enforced():
    gate = PostingGate(daily_max=10, posted_today=10)
    r = gate.check("new_video")
    assert not r.ok
    assert any("상한" in e for e in r.errors)
    assert gate.remaining == 0


def test_warns_when_almost_at_limit():
    gate = PostingGate(daily_max=10, posted_today=9)
    r = gate.check("new_video")
    assert r.ok
    assert any("1개 남았" in w for w in r.warnings)


def test_remaining_never_negative():
    assert PostingGate(daily_max=10, posted_today=99).remaining == 0


# --- 설정 연결 (문서에만 있는 기능이 되지 않게) ---

def test_disclosure_setting_is_wired_to_env(monkeypatch, tmp_path):
    """README 에 적은 AGENT_REQUIRE_DISCLOSURE 가 실제로 동작해야 한다."""
    import importlib
    from app import config as C

    monkeypatch.setattr(C, "PROJECT_ROOT", tmp_path)  # .env 를 읽지 않게
    monkeypatch.setenv("AGENT_REQUIRE_DISCLOSURE", "false")
    assert C.load_settings().require_disclosure is False

    monkeypatch.setenv("AGENT_REQUIRE_DISCLOSURE", "true")
    assert C.load_settings().require_disclosure is True

    monkeypatch.delenv("AGENT_REQUIRE_DISCLOSURE")
    assert C.load_settings().require_disclosure is True  # 기본값은 켜짐
