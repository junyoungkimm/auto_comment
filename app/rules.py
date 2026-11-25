"""댓글 검증과 게시 제한. 요구사항: "운영 규칙 — 코드에서 강제".

지켜야 할 규칙
  - 40~120자
  - 금지: 링크 · 해시태그 · 운명원을 직접 이용해 본 것처럼 지어낸 후기
  - 영상당 댓글 1개
  - 하루 게시 상한 (기본 10개)

추가 규칙 (이 프로젝트의 설계 판단)
  - 광고 표기: 홍보 목적임을 드러내는 문구가 있어야 한다.
    표시광고법상 경제적 이해관계가 있는 추천은 공개해야 하므로 코드에서 강제한다.
    끄려면 .env 의 AGENT_REQUIRE_DISCLOSURE=false
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LINK_PATTERNS = [
    re.compile(r"https?://", re.I),
    re.compile(r"\bwww\.", re.I),
    re.compile(r"\b[\w-]+\.(?:com|net|co\.kr|kr|io|me|ly)\b", re.I),
]
HASHTAG_PATTERN = re.compile(r"(?:^|\s)#\S+")

# "운명원에 가봤다 / 봐봤다" 류의 직접 경험 서술 (금지 항목)
EXPERIENCE_PATTERNS = [
    re.compile(p) for p in [
        r"(가|받아|보|봐|써|이용해)\s*(봤|밨)",
        r"후기",
        r"다녀왔",
        r"경험담",
        r"내돈내산",
    ]
]

# 광고임을 밝히는 표현 (하나라도 있으면 통과)
DISCLOSURE_MARKERS = [
    "광고", "홍보", "협찬", "유료", "제휴", "AD", "ad", "스폰",
]


@dataclass
class Validation:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _has_experience_claim(text: str, brand: str) -> bool:
    """브랜드를 직접 이용해 봤다는 서술이 있는지 (금지 항목)."""
    if brand not in text:
        return False
    # 브랜드 언급 주변 40자 안에서 경험 서술을 찾는다
    for m in re.finditer(re.escape(brand), text):
        window = text[m.start() : m.end() + 40]
        if any(p.search(window) for p in EXPERIENCE_PATTERNS):
            return True
    return False


def validate_comment(
    text: str,
    *,
    brand: str = "운명원",
    min_chars: int = 40,
    max_chars: int = 120,
    require_disclosure: bool = True,
) -> Validation:
    """댓글 본문이 규칙을 지키는지 검사한다."""
    v = Validation()
    body = (text or "").strip()

    # 길이
    n = len(body)
    if n < min_chars:
        v.errors.append(f"길이 미달: {n}자 (최소 {min_chars}자)")
    elif n > max_chars:
        v.errors.append(f"길이 초과: {n}자 (최대 {max_chars}자)")

    # 링크 금지
    if any(p.search(body) for p in LINK_PATTERNS):
        v.errors.append("링크가 포함되어 있습니다 (금지 항목)")

    # 해시태그 금지
    if HASHTAG_PATTERN.search(body):
        v.errors.append("해시태그가 포함되어 있습니다 (금지 항목)")

    # 지어낸 후기 금지
    if _has_experience_claim(body, brand):
        v.errors.append(f"'{brand}'를 직접 이용해 본 것처럼 쓰여 있습니다 (금지 항목)")

    # 광고 표기
    if require_disclosure and not any(m in body for m in DISCLOSURE_MARKERS):
        v.errors.append(
            "광고 표기가 없습니다. 홍보성 댓글은 그 사실을 드러내야 합니다 "
            "(끄려면 AGENT_REQUIRE_DISCLOSURE=false)"
        )

    # 브랜드가 아예 없으면 홍보 목적을 달성 못 하므로 경고
    if brand not in body:
        v.warnings.append(f"'{brand}'가 언급되지 않았습니다")

    return v


@dataclass
class PostingGate:
    """게시 가능 여부. 영상당 1개 · 하루 상한을 코드에서 막는다."""

    daily_max: int = 10
    posted_today: int = 0
    posted_video_ids: frozenset[str] = frozenset()

    def check(self, video_id: str) -> Validation:
        v = Validation()
        if video_id in self.posted_video_ids:
            v.errors.append("이 영상에는 이미 댓글을 달았습니다 (영상당 1개)")
        if self.posted_today >= self.daily_max:
            v.errors.append(
                f"하루 게시 상한에 도달했습니다 ({self.posted_today}/{self.daily_max})"
            )
        remaining = self.daily_max - self.posted_today
        if 0 < remaining <= 2:
            v.warnings.append(f"오늘 {remaining}개 남았습니다")
        return v

    @property
    def remaining(self) -> int:
        return max(self.daily_max - self.posted_today, 0)
