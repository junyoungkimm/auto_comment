"""활동 기록 (JSONL).

요구사항: "어느 영상에 · 어느 프로필로 · 무슨 댓글을 · 성공/실패를 시간순으로".

하루 10개 규모라 DB 대신 추가 전용(append-only) 파일을 쓴다.
파일이 곧 감사 로그라 사람이 바로 열어볼 수 있다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from app.rules import PostingGate

Status = Literal["posted", "failed", "draft", "skipped"]


@dataclass
class Record:
    video_id: str
    video_title: str
    profile: str
    comment: str
    status: Status
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: str | None = None
    screenshot: str | None = None
    method: str | None = None   # typing(브라우저 타이핑) | api(공식 API)

    @property
    def dt(self) -> datetime:
        return datetime.fromisoformat(self.ts)

    @property
    def local_time(self) -> str:
        return self.dt.astimezone().strftime("%m/%d %H:%M")


class ActivityLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: Record) -> Record:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        return record

    def __iter__(self) -> Iterator[Record]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield Record(**json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    continue  # 깨진 줄은 건너뛴다 (기록 전체를 잃지 않게)

    def all(self) -> list[Record]:
        return list(self)

    def recent(self, limit: int = 50) -> list[Record]:
        """최신순. 화면의 기록 패널에 그대로 쓴다."""
        return sorted(self, key=lambda r: r.ts, reverse=True)[:limit]

    # --- 게시 제한 계산 ---

    def posted_records(self) -> list[Record]:
        """실제로 게시된 것만. 초안·실패는 상한에 포함하지 않는다."""
        return [r for r in self if r.status == "posted"]

    def posted_today(self, now: datetime | None = None) -> list[Record]:
        now = (now or datetime.now(timezone.utc)).astimezone()
        today = now.date()
        return [r for r in self.posted_records() if r.dt.astimezone().date() == today]

    def posted_video_ids(self) -> frozenset[str]:
        return frozenset(r.video_id for r in self.posted_records())

    def gate(self, daily_max: int, now: datetime | None = None) -> PostingGate:
        """현재 기록으로 게시 제한 상태를 만든다."""
        return PostingGate(
            daily_max=daily_max,
            posted_today=len(self.posted_today(now)),
            posted_video_ids=self.posted_video_ids(),
        )
