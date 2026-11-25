"""계정(크롬 프로필) 상태와 배정.

기능: "계정1~3 중 고르기 또는 영상마다 돌아가며 자동 배정".

  - 고르기   : 화면에서 계정을 직접 고른다
  - 자동 배정 : 준비된 계정을 영상마다 돌아가며 쓴다 (직전에 게시한 계정의 다음 차례)

배정과 상관없이 지키는 것
  - 한 영상에는 계정 하나만 (PostingGate: 어느 계정이든 영상당 1개)
  - 하루 상한은 계정 합계 기준 (계정을 늘려도 게시량은 늘지 않는다)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

AUTO = "auto"


@dataclass(frozen=True)
class ProfileStatus:
    name: str
    has_browser: bool   # 크롬 프로필 폴더가 만들어져 있다 (자동 입력 게시에 필요)
    has_token: bool     # 공식 API 인증 토큰이 있다 (API 게시에 필요)

    def ready_for(self, method: str) -> bool:
        return self.has_token if method == "api" else self.has_browser

    def missing_for(self, method: str) -> str:
        """준비가 안 됐을 때 사람이 할 일."""
        if method == "api":
            return f"python scripts/auth_youtube.py {self.name} 로 인증하세요"
        return f"python scripts/setup_profile.py {self.name} 로 크롬 프로필을 만들고 로그인하세요"


def profile_status(names: Iterable[str], profiles_dir: Path, token_path) -> list[ProfileStatus]:
    """크롬은 첫 실행 때 Default 폴더를 만든다. 그게 있으면 프로필이 준비된 것으로 본다."""
    return [
        ProfileStatus(
            name=n,
            has_browser=(profiles_dir / n / "Default").is_dir(),
            has_token=Path(token_path(n)).exists(),
        )
        for n in names
    ]


def next_profile(
    statuses: list[ProfileStatus], posted_profiles: list[str], method: str
) -> str | None:
    """영상마다 돌아가며 배정. posted_profiles 는 게시된 순서대로의 계정 이름.

    직전에 게시한 계정의 다음 차례를 고른다. 준비된 계정이 없으면 None.
    """
    ready = [s.name for s in statuses if s.ready_for(method)]
    if not ready:
        return None
    for last in reversed(posted_profiles):
        if last in ready:
            return ready[(ready.index(last) + 1) % len(ready)]
    return ready[0]
