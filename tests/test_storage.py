# -*- coding: utf-8 -*-
"""기록과 게시 제한 연동 테스트."""

from datetime import datetime, timedelta, timezone

from app.storage import ActivityLog, Record


def log_at(path, days_ago=0, **kw):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    defaults = dict(
        video_id="vid1", video_title="제목", profile="계정1",
        comment="댓글", status="posted", ts=ts,
    )
    defaults.update(kw)
    return ActivityLog(path).append(Record(**defaults))


def test_append_and_read_roundtrip(tmp_path):
    path = tmp_path / "activity.jsonl"
    log_at(path, video_id="a", comment="한글 댓글 ✓")

    records = ActivityLog(path).all()

    assert len(records) == 1
    assert records[0].video_id == "a"
    assert records[0].comment == "한글 댓글 ✓"


def test_reading_missing_file_returns_empty(tmp_path):
    assert ActivityLog(tmp_path / "none.jsonl").all() == []


def test_corrupt_line_is_skipped(tmp_path):
    path = tmp_path / "activity.jsonl"
    log_at(path, video_id="good")
    path.open("a", encoding="utf-8").write("{깨진 줄\n")
    log_at(path, video_id="good2")

    ids = [r.video_id for r in ActivityLog(path)]

    assert ids == ["good", "good2"]  # 깨진 줄 하나 때문에 전체를 잃지 않는다


def test_recent_is_newest_first(tmp_path):
    path = tmp_path / "activity.jsonl"
    log_at(path, video_id="old", days_ago=2)
    log_at(path, video_id="new", days_ago=0)

    assert [r.video_id for r in ActivityLog(path).recent()] == ["new", "old"]


# --- 게시 제한 연동 ---

def test_only_posted_counts_toward_daily_limit(tmp_path):
    path = tmp_path / "activity.jsonl"
    log_at(path, video_id="a", status="posted")
    log_at(path, video_id="b", status="draft")
    log_at(path, video_id="c", status="failed")

    gate = ActivityLog(path).gate(daily_max=10)

    assert gate.posted_today == 1  # 초안·실패는 상한에 안 들어간다
    assert gate.remaining == 9


def test_yesterdays_posts_do_not_count_today(tmp_path):
    path = tmp_path / "activity.jsonl"
    log_at(path, video_id="old", days_ago=1)

    gate = ActivityLog(path).gate(daily_max=10)

    assert gate.posted_today == 0


def test_gate_blocks_already_commented_video(tmp_path):
    path = tmp_path / "activity.jsonl"
    log_at(path, video_id="done", status="posted")

    gate = ActivityLog(path).gate(daily_max=10)

    assert not gate.check("done").ok
    assert gate.check("other").ok


def test_draft_does_not_block_the_video(tmp_path):
    """초안만 만들어둔 영상은 아직 게시 안 한 것이므로 막히면 안 된다."""
    path = tmp_path / "activity.jsonl"
    log_at(path, video_id="drafted", status="draft")

    assert ActivityLog(path).gate(daily_max=10).check("drafted").ok


def test_daily_limit_reached(tmp_path):
    path = tmp_path / "activity.jsonl"
    for i in range(10):
        log_at(path, video_id=f"v{i}", status="posted")

    gate = ActivityLog(path).gate(daily_max=10)

    assert not gate.check("new").ok
    assert gate.remaining == 0
