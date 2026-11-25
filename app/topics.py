"""영상이 연애 고민을 다루는지 판단한다.

채널을 연애 쪽으로 골라도 목록에는 다른 주제가 섞인다
(예: "딸 때린 아이 찾아가서 참교육" — 같은 채널이지만 연애 고민이 아니다).
연애가 아닌 영상에 댓글을 달면 맥락이 어긋나므로 걸러낸다.

판단은 제목과 자막 앞부분의 키워드로 한다. 한국어는 조사가 붙으므로
부분 문자열로 찾는다 ("남자친구가" 안에 "남자친구"가 들어 있다).
"""

from __future__ import annotations

from dataclasses import dataclass

# 연애 고민을 가리키는 말. 가중치가 높을수록 확실한 신호다.
STRONG_TERMS = (
    "이별", "재회", "헤어", "짝사랑", "썸", "고백", "밀당", "읽씹", "잠수",
    "남자친구", "여자친구", "남친", "여친", "전남친", "전여친", "전애인",
    "소개팅", "권태기", "환승", "바람피", "미련", "집착", "매달리",
    "연애", "애인", "모쏠", "솔로탈출", "재혼", "이혼",
)

WEAK_TERMS = (
    "마음", "심리", "연락", "데이트", "커플", "호감", "설렘", "상처",
    "결혼", "고민", "사랑", "관계", "차였", "거절", "인연", "만남",
    # "편한 친구 사이에서 발전하기" 처럼 강한 말이 없는 연애 영상을 위해
    "친구 사이", "발전", "사귀", "이성", "연인", "플러팅", "매력",
    # 남녀 심리 영상은 "여자/남자 + 심리·호감" 꼴이 많다
    # ("여자가 당신에게 호감 있을 때" 같은 제목이 통째로 걸러지던 문제)
    "여자", "남자", "여성", "남성", "꼬시", "꼬실", "끌리", "밀어내",
    "똥차", "어장", "금사빠", "결혼정보", "맞선", "데이팅",
)

STRONG_WEIGHT = 2
WEAK_WEIGHT = 1
RELEVANT_THRESHOLD = 2  # 강한 말 1개 또는 약한 말 2개


@dataclass(frozen=True)
class Relevance:
    score: int
    matched: tuple[str, ...]

    @property
    def is_relevant(self) -> bool:
        return self.score >= RELEVANT_THRESHOLD

    @property
    def label(self) -> str:
        if self.score >= 6:
            return "연애 고민"
        if self.is_relevant:
            return "연애 관련"
        return "연애 주제 아님"


def score_text(*parts: str) -> Relevance:
    """제목·설명·자막 조각을 받아 연애 관련도를 매긴다."""
    text = " ".join(p for p in parts if p)
    if not text.strip():
        return Relevance(score=0, matched=())

    matched: list[str] = []
    score = 0
    for term in STRONG_TERMS:
        if term in text:
            score += STRONG_WEIGHT
            matched.append(term)
    for term in WEAK_TERMS:
        if term in text:
            score += WEAK_WEIGHT
            matched.append(term)
    return Relevance(score=score, matched=tuple(matched))


def score_video(title: str, description: str = "", transcript_head: str = "") -> Relevance:
    """영상 하나의 연애 관련도.

    제목이 가장 믿을 만한 신호라 제목만으로도 판단되게 하고,
    자막이 캐시돼 있으면 앞부분을 보조로 쓴다.
    """
    return score_text(title, description, transcript_head[:600])
