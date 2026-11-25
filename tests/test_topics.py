# -*- coding: utf-8 -*-
"""연애 주제 판별 테스트. 실제 채널에서 나온 제목으로 검증한다."""

import pytest

from app.topics import score_text, score_video

# 실제 RSS 에서 가져온 제목들
REAL_RELEVANT = [
    '이별 후 "그만 연락해" 라는 단호한 전애인, 이 한마디면 무너집니다! | 재회 연락에서 절대 놓치지 말아야 할 것',
    "남자가 이별 후 다시 나를 사랑하게 만드는 방법(남자가 진심으로 여자를 원할 때)",
    "연말 재회 더 어려워지는 진짜 이유 💔 크리스마스 전 필승 준비법",
    "연애 초반 모습으로 돌아가면 재회 망합니다",
    "갑자기 이별통보 당했다면? 이 심리입니다 재회가능성",
    "편한 친구 사이에서 발전하기",
    "모쏠이 모쏠이라고 느껴지는 순간",
]

REAL_IRRELEVANT = [
    "이게 부모의 마음이지.. 딸 때린 아이 찾아가서 참교육",
    "오늘 점심 뭐 먹지 고민될 때 보는 영상",
    "2026년 부동산 전망 총정리",
]


@pytest.mark.parametrize("title", REAL_RELEVANT)
def test_real_dating_titles_are_relevant(title):
    r = score_video(title)
    assert r.is_relevant, f"score={r.score} matched={r.matched}"


@pytest.mark.parametrize("title", REAL_IRRELEVANT)
def test_real_off_topic_titles_are_filtered(title):
    r = score_video(title)
    assert not r.is_relevant, f"score={r.score} matched={r.matched}"


def test_strong_term_alone_is_enough():
    """'이별' 하나만 있어도 연애 영상으로 본다."""
    assert score_video("이별 극복법").is_relevant


def test_single_weak_term_is_not_enough():
    """'마음' 하나로는 연애 영상이라 단정할 수 없다."""
    r = score_video("마음 다스리는 법")
    assert not r.is_relevant


def test_two_weak_terms_pass():
    r = score_video("상처받은 마음 치유하기")
    assert r.is_relevant


def test_korean_particles_do_not_break_matching():
    """조사가 붙어도 찾아야 한다."""
    r = score_video("남자친구가 연락을 안 해요")
    assert r.is_relevant
    assert "남자친구" in r.matched


def test_empty_input():
    r = score_video("")
    assert r.score == 0
    assert not r.is_relevant
    assert r.label == "연애 주제 아님"


def test_transcript_helps_when_title_is_vague():
    """제목이 모호해도 자막에 단서가 있으면 건진다."""
    vague = "3화"
    assert not score_video(vague).is_relevant
    assert score_video(vague, transcript_head="오늘 사연은 헤어진 남자친구 얘기입니다").is_relevant


def test_transcript_is_truncated():
    """자막 전체를 넣어도 앞부분만 본다 (뒤쪽 잡담에 휘둘리지 않게)."""
    tail_only = "가" * 1000 + " 이별 재회 썸"
    assert not score_video("제목", transcript_head=tail_only).is_relevant


def test_labels():
    assert score_video("오늘 날씨").label == "연애 주제 아님"
    assert score_video("이별 후 재회 가능성과 전남친 심리 연락 밀당").label == "연애 고민"


def test_matched_terms_are_reported():
    r = score_text("이별 후 재회")
    assert "이별" in r.matched
    assert "재회" in r.matched


def test_channel_boilerplate_must_not_be_used_as_a_signal():
    """RSS 설명란은 채널 고정 안내문이라 모든 영상을 통과시킨다.

    실제로 겪은 문제: 설명을 점수에 넣었더니 75개 중 0개만 걸러졌다.
    설명은 영상이 아니라 채널 주제를 알려줄 뿐이므로 쓰지 않는다.
    """
    boilerplate = "내 연애를 구해줘! 연애상담소 #연애조정위원회 #여자심리 #남자심리 #재회상담"
    off_topic_title = "오늘 점심 뭐 먹지"

    # 제목만 보면 연애가 아니다
    assert not score_video(off_topic_title).is_relevant
    # 설명을 섞으면 통과해 버린다 — 그래서 섞지 않는다
    assert score_text(off_topic_title, boilerplate).is_relevant


def test_transcript_head_is_a_valid_signal():
    """자막은 그 영상의 실제 내용이므로 보조 근거로 쓴다."""
    assert score_video("난 왜 또 이럴까", transcript_head="오늘은 전남친 재회 얘기").is_relevant
