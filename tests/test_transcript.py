# -*- coding: utf-8 -*-
"""자막 포맷·폴백 로직 테스트. 네트워크를 쓰지 않는다."""

from app.transcript import Snippet, TranscriptResult


def make_result(n: int = 3) -> TranscriptResult:
    return TranscriptResult(
        video_id="abc12345678",
        snippets=[Snippet(start=i * 61.0, text=f"문장{i}") for i in range(n)],
        language="ko",
        is_generated=False,
    )


# --- 타임스탬프 ---

def test_timestamp_format():
    assert Snippet(start=0.0, text="x").timestamp == "0:00"
    assert Snippet(start=61.0, text="x").timestamp == "1:01"
    assert Snippet(start=252.4, text="x").timestamp == "4:12"
    assert Snippet(start=3600.0, text="x").timestamp == "60:00"


def test_prompt_text_includes_timestamps():
    text = make_result().as_prompt_text()

    # AI가 "4:12 장면" 처럼 짚으려면 타임스탬프가 본문에 있어야 한다
    assert "[0:00] 문장0" in text
    assert "[1:01] 문장1" in text
    assert "[2:02] 문장2" in text


def test_prompt_text_truncates_long_transcripts_keeping_both_ends():
    long_result = TranscriptResult(
        video_id="x",
        snippets=[Snippet(start=float(i), text="가" * 50) for i in range(300)],
    )

    text = long_result.as_prompt_text(max_chars=1000)

    assert len(text) < 1300          # 한도 + 중략 표시 정도
    assert "...(중략)..." in text
    assert text.startswith("[0:00]")  # 도입부 유지
    assert "299" in text or "가" in text[-100:]  # 마지막 부분도 유지


def test_prompt_text_keeps_short_transcript_intact():
    text = make_result().as_prompt_text(max_chars=6000)
    assert "중략" not in text


# --- 가용 여부 ---

def test_available_flag():
    assert make_result().available is True
    assert TranscriptResult(video_id="x", error="TranscriptsDisabled").available is False


def test_full_text_joins_snippets():
    assert make_result().full_text == "문장0 문장1 문장2"


# --- 캐시 (IP 차단 대비) ---

def test_cache_roundtrip(tmp_path, monkeypatch):
    from app import transcript as T

    monkeypatch.setattr(T, "CACHE_DIR", tmp_path)
    original = make_result(4)
    T.save_cache(original)

    loaded = T.load_cached(original.video_id)

    assert loaded is not None
    assert loaded.cached is True
    assert [s.text for s in loaded.snippets] == [s.text for s in original.snippets]
    assert [s.start for s in loaded.snippets] == [s.start for s in original.snippets]
    assert loaded.language == "ko"


def test_failed_fetch_is_not_cached(tmp_path, monkeypatch):
    """실패를 캐시하면 차단이 풀려도 계속 실패한 결과를 쓰게 된다."""
    from app import transcript as T

    monkeypatch.setattr(T, "CACHE_DIR", tmp_path)
    T.save_cache(TranscriptResult(video_id="blocked", error="IpBlocked"))

    assert T.load_cached("blocked") is None


def test_missing_cache_returns_none(tmp_path, monkeypatch):
    from app import transcript as T

    monkeypatch.setattr(T, "CACHE_DIR", tmp_path)
    assert T.load_cached("neverfetched") is None


def test_corrupt_cache_returns_none(tmp_path, monkeypatch):
    from app import transcript as T

    monkeypatch.setattr(T, "CACHE_DIR", tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")

    assert T.load_cached("broken") is None


def test_cache_hit_skips_network(tmp_path, monkeypatch):
    from app import transcript as T

    monkeypatch.setattr(T, "CACHE_DIR", tmp_path)
    T.save_cache(make_result(2))

    def boom(*a, **k):
        raise AssertionError("캐시가 있으면 네트워크를 쓰면 안 된다")

    monkeypatch.setattr(T.YouTubeTranscriptApi, "fetch", boom)

    result = T.fetch_transcript("abc12345678")

    assert result.available
    assert result.cached
