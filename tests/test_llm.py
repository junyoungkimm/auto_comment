# -*- coding: utf-8 -*-
"""데모 분석기 테스트. 핵심은 '초안이 운영 규칙을 통과하는가'."""

import pytest

from app.llm import DemoAnalyzer, get_analyzer
from app.rules import validate_comment
from app.transcript import Snippet, TranscriptResult


def transcript(texts_with_times) -> TranscriptResult:
    return TranscriptResult(
        video_id="vid",
        snippets=[Snippet(start=t, text=x) for t, x in texts_with_times],
        language="ko",
    )


ROMANCE = transcript([
    (0.0, "안녕하세요 구독자 여러분"),
    (61.0, "오늘은 읽씹하는 남자 심리를 다뤄볼게요"),
    (252.0, "연락이 뜸해지면 마음이 식은 걸까요"),
    (400.0, "구독과 좋아요 부탁드립니다"),
])


def test_draft_passes_all_operating_rules():
    a = DemoAnalyzer().analyze(title="읽씹하는 남자 심리", channel="채널", transcript=ROMANCE)

    result = validate_comment(a.draft)

    assert result.ok, f"{result.errors}\n초안: {a.draft}"


def test_draft_length_is_within_40_120():
    a = DemoAnalyzer().analyze(title="읽씹하는 남자 심리", channel="채널", transcript=ROMANCE)
    assert 40 <= len(a.draft) <= 120


def test_quote_comes_from_the_transcript():
    a = DemoAnalyzer().analyze(title="제목", channel="채널", transcript=ROMANCE)

    assert a.quote
    assert any(a.quote in s.text for s in ROMANCE.snippets)
    assert a.quote_timestamp in a.draft  # 초안이 실제 장면을 짚는다


def test_prefers_a_line_about_a_dating_concern():
    """인사말이나 구독 안내가 아니라 고민이 담긴 대목을 골라야 한다."""
    a = DemoAnalyzer().analyze(title="제목", channel="채널", transcript=ROMANCE)

    assert "구독" not in a.quote
    assert "안녕하세요" not in a.quote


def test_different_videos_give_different_drafts():
    """맥락 이해 항목이 '영상마다 다른가'를 보므로 같은 결과가 나오면 안 된다."""
    other = transcript([(30.0, "소개팅에서 첫인상이 중요한 이유")])

    a1 = DemoAnalyzer().analyze(title="A", channel="c", transcript=ROMANCE)
    a2 = DemoAnalyzer().analyze(title="B", channel="c", transcript=other)

    assert a1.draft != a2.draft


def test_works_without_transcript():
    a = DemoAnalyzer().analyze(
        title="남자 심리 분석", channel="채널", transcript=TranscriptResult(video_id="v")
    )

    assert validate_comment(a.draft).ok
    assert any("자막이 없어" in n for n in a.notes)


def test_very_long_quote_still_fits_length_limit():
    long_tr = transcript([(100.0, "연락이 " + "가" * 200)])

    a = DemoAnalyzer().analyze(title="제목", channel="채널", transcript=long_tr)

    assert len(a.draft) <= 120
    assert validate_comment(a.draft).ok, validate_comment(a.draft).errors


def test_demo_is_flagged_as_demo():
    a = DemoAnalyzer().analyze(title="t", channel="c", transcript=ROMANCE)
    assert a.is_demo
    assert a.source == "demo"


def test_get_analyzer_rejects_unknown_provider():
    with pytest.raises(ValueError, match="지원하지 않는"):
        get_analyzer("gpt4")


# --- 없는 장면을 있는 것처럼 표시하지 않기 ---

class _FakeGemini(DemoAnalyzer):
    """제미나이가 내놓은 JSON 을 흉내내어 후처리만 검증한다."""


def test_quote_is_dropped_when_there_is_no_source_text(monkeypatch):
    """자막도 설명도 없으면 인용할 원문이 없다. 근거 자체를 지운다."""
    from app.llm import GeminiAnalyzer
    import httpx

    payload = {
        "candidates": [{"content": {"parts": [{"text":
            '{"concern":"고민","quote":"제목에서 가져온 말",'
            '"quote_timestamp":"0:00","draft":"' + "가" * 50 + ' 운명원 (광고)"}'
        }]}}]
    }

    class R:
        status_code = 200
        text = ""
        def json(self): return payload

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())

    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=TranscriptResult(video_id="v")
    )

    assert a.quote_timestamp == ""   # 0:00 을 그대로 쓰면 안 된다
    assert a.quote == ""              # 확인할 원문이 없으므로 근거도 비운다
    assert any("원문에 없는" in n for n in a.notes)


def test_quote_not_found_in_transcript_is_dropped(monkeypatch):
    """자막이 있는데 거기 없는 말을 인용했다면 지어낸 것이다."""
    from app.llm import GeminiAnalyzer
    import httpx

    payload = {
        "candidates": [{"content": {"parts": [{"text":
            '{"concern":"고민","quote":"자막에 없는 문장",'
            '"quote_timestamp":"4:12","draft":"' + "가" * 50 + ' 운명원 (광고)"}'
        }]}}]
    }

    class R:
        status_code = 200
        text = ""
        def json(self): return payload

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())

    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=ROMANCE
    )

    assert a.quote_timestamp == ""
    assert a.quote == ""
    assert any("원문에 없는" in n for n in a.notes)


def test_timestamp_is_kept_when_quote_really_is_in_transcript(monkeypatch):
    from app.llm import GeminiAnalyzer
    import httpx

    real = ROMANCE.snippets[1].text
    payload = {
        "candidates": [{"content": {"parts": [{"text":
            '{"concern":"고민","quote":"' + real + '",'
            '"quote_timestamp":"1:01","draft":"' + "가" * 50 + ' 운명원 (광고)"}'
        }]}}]
    }

    class R:
        status_code = 200
        text = ""
        def json(self): return payload

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())

    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=ROMANCE
    )

    assert a.quote_timestamp == "1:01"


def test_invented_quote_is_removed(monkeypatch):
    """원문 어디에도 없는 문장을 인용하면 근거에서 빼버린다."""
    from app.llm import GeminiAnalyzer
    import httpx

    payload = {"candidates": [{"content": {"parts": [{"text":
        '{"concern":"고민","quote":"아무도 한 적 없는 말",'
        '"quote_timestamp":"2:00","draft":"' + "가" * 50 + ' 운명원 (광고)"}'
    }]}}]}

    class R:
        status_code = 200
        text = ""
        def json(self): return payload

    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())

    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널",
        transcript=TranscriptResult(video_id="v"), description="설명글입니다",
    )

    assert a.quote == ""
    assert a.quote_timestamp == ""
    assert any("원문에 없는" in n for n in a.notes)


def test_quote_from_description_keeps_text_but_drops_timestamp():
    """설명글에서 인용하는 건 괜찮다. 다만 영상 속 시각은 없다."""
    from app.llm import GeminiAnalyzer
    import httpx, pytest

    desc = "이번 영상은 연락이 뜸해진 연인에 대한 이야기입니다"
    payload = {"candidates": [{"content": {"parts": [{"text":
        '{"concern":"고민","quote":"연락이 뜸해진 연인",'
        '"quote_timestamp":"1:00","draft":"' + "가" * 50 + ' 운명원 (광고)"}'
    }]}}]}

    class R:
        status_code = 200
        text = ""
        def json(self): return payload

    import app.llm as L
    original = httpx.post
    httpx.post = lambda *a, **k: R()
    try:
        a = GeminiAnalyzer(api_key="x").analyze(
            title="제목", channel="채널",
            transcript=TranscriptResult(video_id="v"), description=desc,
        )
    finally:
        httpx.post = original

    assert a.quote == "연락이 뜸해진 연인"
    assert a.quote_timestamp == ""


# --- 모델 과부하 대응 ---

def _json_response(status=200, text='{"concern":"c","quote":"","quote_timestamp":"","draft":"' + "가" * 50 + ' 운명원 (광고)"}'):
    class R:
        status_code = status
        def __init__(self): self.text = text
        def json(self): return {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return R()


def test_falls_back_to_second_model_on_503(monkeypatch):
    """gemini-3.5-flash 가 503 high demand 를 내던 실제 상황."""
    from app.llm import GeminiAnalyzer

    used = []

    def fake_call(self, model, prompt):
        used.append(model)
        return _json_response(503 if model == "primary" else 200)

    monkeypatch.setattr(GeminiAnalyzer, "_call", fake_call)

    a = GeminiAnalyzer(api_key="x", model="primary", fallback_model="backup").analyze(
        title="제목", channel="채널", transcript=ROMANCE
    )

    assert used == ["primary", "backup"]
    assert any("backup 로 처리" in n for n in a.notes)


def test_falls_back_on_timeout(monkeypatch):
    from app.llm import GeminiAnalyzer

    def fake_call(self, model, prompt):
        if model == "primary":
            raise TimeoutError("read timed out")
        return _json_response(200)

    monkeypatch.setattr(GeminiAnalyzer, "_call", fake_call)

    a = GeminiAnalyzer(api_key="x", model="primary", fallback_model="backup").analyze(
        title="제목", channel="채널", transcript=ROMANCE
    )
    assert a.source == "gemini"


def test_does_not_retry_on_bad_key(monkeypatch):
    """401/400 은 재시도해도 같은 결과다. 대체 모델을 괜히 때리지 않는다."""
    from app.llm import GeminiAnalyzer

    used = []

    def fake_call(self, model, prompt):
        used.append(model)
        return _json_response(401)

    monkeypatch.setattr(GeminiAnalyzer, "_call", fake_call)

    with pytest.raises(RuntimeError, match="호출 실패"):
        GeminiAnalyzer(api_key="bad", model="primary", fallback_model="backup").analyze(
            title="제목", channel="채널", transcript=ROMANCE
        )

    assert used == ["primary"]


# --- 길이 초과 시 자동 축약 ---

def test_too_long_draft_is_shortened(monkeypatch):
    from app.llm import GeminiAnalyzer

    long_draft = "가" * 150 + " 운명원 (광고)"
    short = "짧게 줄인 댓글입니다. " * 2 + "운명원 연애사주 궁금하네요. (광고)"

    monkeypatch.setattr(GeminiAnalyzer, "_call", lambda self, m, p: _json_response(
        200, '{"concern":"c","quote":"","quote_timestamp":"","draft":"' + long_draft + '"}'))
    monkeypatch.setattr(GeminiAnalyzer, "_call_text", lambda self, m, p: short)

    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=ROMANCE
    )

    assert a.draft == short
    assert len(a.draft) <= 120


def test_failed_shortening_keeps_original_and_warns(monkeypatch):
    """줄이기가 실패하면 원문을 두고 사람에게 알린다 (조용히 자르지 않는다)."""
    from app.llm import GeminiAnalyzer

    long_draft = "가" * 150 + " 운명원 (광고)"
    monkeypatch.setattr(GeminiAnalyzer, "_call", lambda self, m, p: _json_response(
        200, '{"concern":"c","quote":"","quote_timestamp":"","draft":"' + long_draft + '"}'))
    monkeypatch.setattr(GeminiAnalyzer, "_call_text", lambda self, m, p: "")

    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=ROMANCE
    )

    assert a.draft == long_draft
    assert any("직접 줄여야" in n for n in a.notes)


def test_shortening_not_triggered_when_within_limit(monkeypatch):
    from app.llm import GeminiAnalyzer

    fine = "가" * 60 + " 운명원 (광고)"
    called = []
    monkeypatch.setattr(GeminiAnalyzer, "_call", lambda self, m, p: _json_response(
        200, '{"concern":"c","quote":"","quote_timestamp":"","draft":"' + fine + '"}'))
    monkeypatch.setattr(GeminiAnalyzer, "_call_text",
                        lambda self, m, p: called.append(1) or "")

    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=ROMANCE
    )

    assert a.draft == fine
    assert called == []  # 불필요한 호출을 하지 않는다


def test_shortening_uses_the_model_that_actually_responded(monkeypatch):
    """주 모델이 503 이면 축약도 대체 모델로 보내야 한다."""
    from app.llm import GeminiAnalyzer

    long_draft = "가" * 150 + " 운명원 (광고)"
    short = "줄인 댓글입니다 " * 4 + "운명원 궁금하네요 (광고)"
    asked = []

    monkeypatch.setattr(GeminiAnalyzer, "_call", lambda self, m, p: _json_response(
        503 if m == "primary" else 200,
        '{"concern":"c","quote":"","quote_timestamp":"","draft":"' + long_draft + '"}'))
    monkeypatch.setattr(GeminiAnalyzer, "_call_text",
                        lambda self, m, p: (asked.append(m), short)[1])

    a = GeminiAnalyzer(api_key="x", model="primary", fallback_model="backup").analyze(
        title="제목", channel="채널", transcript=ROMANCE
    )

    assert asked == ["backup"]   # primary 가 아니라 backup 으로 물어봐야 한다
    assert a.draft == short


# --- 인기 댓글 ---

def test_top_comments_reach_prompt(monkeypatch):
    """과제 요구: 자막과 인기 댓글을 함께 읽는다."""
    from app.llm import GeminiAnalyzer

    prompts = []

    def fake_call(self, model, prompt):
        prompts.append(prompt)
        return _json_response(200)

    monkeypatch.setattr(GeminiAnalyzer, "_call", fake_call)
    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=ROMANCE,
        top_comments=["읽씹 당한 사람 손", "3분 대목 소름"],
    )
    assert "[인기 댓글]" in prompts[0]
    assert "- 읽씹 당한 사람 손" in prompts[0]
    assert any("인기 댓글 2개" in n for n in a.notes)


def test_quote_from_comment_is_dropped(monkeypatch):
    """근거 인용은 영상에서만. 댓글 문장을 근거로 띄우지 않는다."""
    import json as _json
    from app.llm import GeminiAnalyzer

    body = _json.dumps({"concern": "c", "quote": "읽씹 당한 사람 손",
                        "quote_timestamp": "1:00", "draft": "가" * 50 + " 운명원 (광고)"})
    monkeypatch.setattr(GeminiAnalyzer, "_call", lambda self, m, p: _json_response(200, body))
    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=ROMANCE, top_comments=["읽씹 당한 사람 손"],
    )
    assert a.quote == "" and a.quote_timestamp == ""


def test_multiple_fallbacks_on_daily_quota(monkeypatch):
    """무료 등급 429(모델별 일일 한도) — 주·대체 모델이 다 막혀도 세 번째 모델로 넘어간다."""
    from app.llm import GeminiAnalyzer

    used = []

    def fake_call(self, model, prompt):
        used.append(model)
        return _json_response(429 if model in ("primary", "second") else 200)

    monkeypatch.setattr(GeminiAnalyzer, "_call", fake_call)
    a = GeminiAnalyzer(api_key="x", model="primary", fallback_model="second, third").analyze(
        title="제목", channel="채널", transcript=ROMANCE
    )
    assert used == ["primary", "second", "third"]
    assert a.source == "gemini"


# --- 자막을 못 받으면 AI가 영상을 직접 본다 ---

def _video_reply(quote, ts):
    import json as _json
    return _json_response(200, _json.dumps({
        "concern": "c", "quote": quote, "quote_timestamp": ts,
        "draft": "가" * 50 + " 운명원 (광고)"}))


def test_watches_video_when_no_transcript(monkeypatch):
    from app.llm import GeminiAnalyzer
    from app.transcript import TranscriptResult

    calls = []

    def fake_call(self, model, prompt, video_url=""):
        calls.append(video_url)
        return _video_reply("이 한마디면 무너집니다", "6:09")

    monkeypatch.setattr(GeminiAnalyzer, "_call", fake_call)
    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=TranscriptResult(video_id="v"),
        video_url="https://www.youtube.com/watch?v=v",
    )
    assert calls == ["https://www.youtube.com/watch?v=v"]
    assert a.watched_video and a.quote_source == "video"
    assert a.quote == "이 한마디면 무너집니다" and a.quote_timestamp == "6:09"


def test_video_quote_without_timestamp_is_dropped(monkeypatch):
    from app.llm import GeminiAnalyzer
    from app.transcript import TranscriptResult

    monkeypatch.setattr(GeminiAnalyzer, "_call",
                        lambda self, m, p, video_url="": _video_reply("지어낸 대사", ""))
    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=TranscriptResult(video_id="v"),
        video_url="https://www.youtube.com/watch?v=v",
    )
    assert a.quote == "" and a.quote_source == ""


def test_transcript_wins_over_video(monkeypatch):
    """자막이 있으면 영상을 보내지 않는다 (토큰 절약, 글자 대조 가능)."""
    from app.llm import GeminiAnalyzer

    calls = []

    def fake_call(self, model, prompt, video_url=""):
        calls.append(video_url)
        return _json_response(200)

    monkeypatch.setattr(GeminiAnalyzer, "_call", fake_call)
    a = GeminiAnalyzer(api_key="x").analyze(
        title="제목", channel="채널", transcript=ROMANCE,
        video_url="https://www.youtube.com/watch?v=v",
    )
    assert calls == [""] and not a.watched_video


def test_video_request_shape():
    """실제 요청 본문: 영상 파트가 앞에, 낮은 해상도, 앞 15분만."""
    import httpx
    from app.llm import GeminiAnalyzer

    captured = {}
    original = httpx.post
    httpx.post = lambda url, **kw: captured.update(kw) or _json_response(200)
    try:
        GeminiAnalyzer(api_key="x")._call("m", "프롬프트", "https://www.youtube.com/watch?v=v")
    finally:
        httpx.post = original
    parts = captured["json"]["contents"][0]["parts"]
    assert parts[0]["file_data"]["file_uri"].endswith("v=v")
    assert parts[0]["video_metadata"]["end_offset"] == "900s"
    assert captured["json"]["generationConfig"]["mediaResolution"] == "MEDIA_RESOLUTION_LOW"
    assert captured["timeout"] == GeminiAnalyzer.VIDEO_TIMEOUT_SECONDS


# --- AI 없이 만든 임시 문구는 게시하지 않는다 ---

def test_placeholder_detection():
    from app.llm import DemoAnalyzer, is_placeholder_draft
    from app.transcript import TranscriptResult

    generic = "영상 내용 공감되네요. 저도 비슷한 고민이라 운명원 연애사주 한번 보고 싶어지네요. (광고)"
    assert is_placeholder_draft(generic)
    assert is_placeholder_draft("  " + generic.replace(" ", "  ") + " ")   # 공백 차이는 무시
    # 데모가 자막 대사를 넣어 만든 것도 같은 틀이다
    demo = DemoAnalyzer().analyze(title="t", channel="c", transcript=ROMANCE).draft
    assert is_placeholder_draft(demo)
    demo_no_sub = DemoAnalyzer().analyze(
        title="t", channel="c", transcript=TranscriptResult(video_id="v")).draft
    assert is_placeholder_draft(demo_no_sub)
    # 사람이 고쳐 쓰면 통과
    assert not is_placeholder_draft(generic.replace("공감되네요", "너무 와닿네요"))
    assert not is_placeholder_draft("단호하게 거절하는 상대 마음… 운명원 연애사주 궁금하네요 (광고)")


def test_unavailable_model_404_moves_to_next(monkeypatch):
    """새 프로젝트 키로는 옛 대체 모델이 404 — 거기서 멈추지 말고 다음 모델로."""
    from app.llm import GeminiAnalyzer

    used = []

    def fake_call(self, model, prompt):
        used.append(model)
        return _json_response({"primary": 503, "old": 404}.get(model, 200))

    monkeypatch.setattr(GeminiAnalyzer, "_call", fake_call)
    a = GeminiAnalyzer(api_key="x", model="primary", fallback_model="old,lite").analyze(
        title="제목", channel="채널", transcript=ROMANCE
    )
    assert used == ["primary", "old", "lite"] and a.source == "gemini"
