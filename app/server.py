"""로컬 대시보드 서버.

내 컴퓨터에서만 돈다 (127.0.0.1). 화면은 web/ 의 정적 파일이고,
아래 API 로 영상 목록 · 분석 · 규칙 검사 · 기록을 주고받는다.

    python -m app.server
"""

from __future__ import annotations

import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.browser import BrowserError, open_in_profile
from app.browser_post import TypingPostError, post_by_typing
from app.capture import capture_screen
from app.discover import discover_rising
from app.profiles import AUTO, next_profile, profile_status
from app.comments import fetch_top_comments
from app.config import PROJECT_ROOT, load_settings
from app.google_auth import token_path
from app.feed import (
    Video,
    extract_video_id,
    fetch_channels,
    fetch_oembed,
    find_rising,
    resolve_channel_id,
)
from app.llm import get_analyzer, is_placeholder_draft
from app.rules import validate_comment
from app.storage import ActivityLog, Record
from app.topics import score_video
from app.transcript import fetch_transcript, load_cached
from app.youtube_post import PostError, find_my_comment, post_and_verify

WEB_DIR = PROJECT_ROOT / "web"

app = FastAPI(title="유튜브 댓글 에이전트")


@app.middleware("http")
async def _no_cache_for_screen(request, call_next):
    """화면 파일을 브라우저가 캐시하지 않게 한다.

    화면을 고친 뒤에도 예전 문구가 보이는 일을 실제로 겪었다 (시연 녹화 전).
    """
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


settings = load_settings()
activity = ActivityLog(settings.log_path)

# 영상 목록 캐시 (RSS 를 매 클릭마다 다시 긁지 않도록)
_videos: dict[str, Video] = {}
_rising_ids: set[str] = set()
# 링크로 직접 넣은 영상 (RSS 목록에 없으므로 따로 들고 있는다)
_link_videos: dict[str, dict] = {}
# '연애' 키워드 검색으로 찾은 영상. 과제 기준이 "초안까지만"이라 게시를 막는다.
_draft_only: set[str] = set()


def _topic_of(video_id: str, title: str) -> "object":
    """영상의 연애 관련도.

    RSS 설명란은 쓰지 않는다. 채널 고정 안내문(상담 링크·해시태그)이 들어 있어서
    영상 내용과 무관하게 전부 통과시킨다 — 영상이 아니라 채널 주제를 알려줄 뿐이다.
    대신 자막이 캐시돼 있으면 앞부분을 보조 근거로 쓴다.
    """
    cached = load_cached(video_id)
    head = cached.full_text[:600] if cached else ""
    return score_video(title, transcript_head=head)


def _video_json(v: Video) -> dict:
    topic = _topic_of(v.video_id, v.title)
    return {
        "topic_score": topic.score,
        "topic_label": topic.label,
        "on_topic": topic.is_relevant,
        "video_id": v.video_id,
        "title": v.title,
        "channel": v.channel,
        "published": v.published.isoformat(),
        "thumbnail": v.thumbnail,
        "views": v.views,
        "views_per_hour": round(v.views_per_hour, 1),
        "age_hours": round(v.age_hours, 1),
        "url": v.url,
        "rising": v.video_id in _rising_ids,
        "commented": v.video_id in activity.posted_video_ids(),
        "draft_only": v.video_id in _draft_only,
    }


def _comment_reader_profile() -> str:
    """인기 댓글을 읽을 때 쓸 프로필. 토큰이 있는 첫 프로필."""
    for p in settings.profiles:
        if token_path(p).exists():
            return p
    return ""


def _statuses():
    return profile_status(settings.profiles, settings.profiles_dir, token_path)


def _next_profile(method: str) -> str | None:
    """영상마다 돌아가며 배정할 다음 계정."""
    posted = [r.profile for r in activity.posted_records()]
    return next_profile(_statuses(), posted, method)


def _resolve_profile(raw: str, method: str) -> str:
    """화면에서 받은 계정 값을 실제 계정으로. 'auto'(또는 빈 값)면 돌아가며 배정한다."""
    if not raw or raw == AUTO:
        chosen = _next_profile(method)
        if chosen is None:
            st = _statuses()[0]
            raise HTTPException(status_code=409,
                                detail=f"준비된 계정이 없습니다. {st.missing_for(method)}")
        return chosen
    st = next((x for x in _statuses() if x.name == raw), None)
    if st is None:
        raise HTTPException(status_code=400, detail=f"알 수 없는 계정입니다: {raw}")
    if not st.ready_for(method):
        raise HTTPException(status_code=409,
                            detail=f"{raw} 은(는) 아직 준비되지 않았습니다. {st.missing_for(method)}")
    return raw


def _explain_ai_failure(e: Exception) -> str:
    text = str(e)
    if "429" in text:
        return "AI 사용량 한도를 모두 썼습니다 (무료 등급은 매일 초기화)"
    if "503" in text or "Timeout" in text:
        return "AI 서버가 응답하지 않습니다 (잠시 후 다시 시도)"
    return f"AI 호출 실패: {text[:100]}"


def _validate_text(text: str):
    """댓글 규칙 + 'AI 없이 만든 임시 문구는 게시 금지'.

    AI 한도가 떨어지면 틀에 박힌 문장이 초안에 들어가는데, 그게 실제로 한 번 게시됐다.
    사람이 손으로 고쳐 쓰면 통과한다.
    """
    check = validate_comment(
        text, brand=settings.brand,
        min_chars=settings.min_chars, max_chars=settings.max_chars,
        require_disclosure=settings.require_disclosure,
    )
    if is_placeholder_draft(text, settings.brand):
        check.errors.append(
            "AI가 초안을 만들지 못해 들어간 임시 문구입니다. 직접 고쳐 쓰거나 [다시 생성]을 눌러주세요"
        )
    return check


def _record_failure(video_id: str, video_title: str, profile: str,
                    comment: str, error: str, screenshot: str | None = None,
                    method: str | None = None) -> Record:
    """실패를 이유 · 화면 캡처와 함께 기록한다 (과제 요구).

    브라우저 캡처가 이미 있으면 그걸 쓰고, 없으면 화면 전체를 찍는다.
    """
    shot = screenshot or capture_screen(settings.screenshot_dir, video_id)
    return activity.append(Record(
        video_id=video_id, video_title=video_title, profile=profile,
        comment=comment, status="failed", error=error, screenshot=shot, method=method,
    ))


def _explain_unexpected(e: Exception) -> str:
    """PostError 가 아닌 예외(인증 만료 등)를 사람이 읽을 말로."""
    name = type(e).__name__
    if name == "RefreshError":
        return "인증이 만료됐습니다. scripts/auth_youtube.py 를 다시 실행하세요."
    return f"{name}: {str(e)[:200]}"


# --- 상태 ---

@app.get("/api/state")
def get_state():
    gate = activity.gate(settings.daily_max_comments)
    return {
        "brand": settings.brand,
        "profiles": [
            {"name": x.name, "has_browser": x.has_browser, "has_token": x.has_token}
            for x in _statuses()
        ],
        "next_profile": {"typing": _next_profile("typing"), "api": _next_profile("api")},
        "channels": list(settings.channels),
        "channels_configured": bool(settings.channels),
        "ai_provider": settings.effective_provider,
        "ai_is_demo": settings.effective_provider == "demo",
        "ai_model": settings.gemini_model if settings.effective_provider == "gemini" else "",
        "limits": {
            "min_chars": settings.min_chars,
            "max_chars": settings.max_chars,
            "daily_max": settings.daily_max_comments,
            "posted_today": gate.posted_today,
            "remaining": gate.remaining,
        },
        "rising_rule": {
            "min_views": settings.rising_min_views,
            "max_views": settings.rising_max_views,
            "min_vph": settings.rising_min_vph,
        },
    }


# --- 1. 영상 불러오기 ---

@app.post("/api/videos/refresh")
def refresh_videos():
    if not settings.channels:
        raise HTTPException(
            status_code=400,
            detail="채널이 설정되지 않았습니다. .env 의 AGENT_CHANNELS 에 "
                   "핸들(@이름) 또는 채널 ID 를 쉼표로 넣어주세요.",
        )
    channel_ids: list[str] = []
    errors: list[dict] = []
    for raw in settings.channels:
        try:
            channel_ids.append(resolve_channel_id(raw))
        except Exception as e:
            errors.append({"channel": raw, "error": str(e)[:160]})

    videos, feed_errors = fetch_channels(channel_ids)
    errors += [{"channel": c, "error": e} for c, e in feed_errors]

    _videos.clear()
    _videos.update({v.video_id: v for v in videos})

    rising = find_rising(
        videos,
        min_views=settings.rising_min_views,
        max_views=settings.rising_max_views,
        min_views_per_hour=settings.rising_min_vph,
    )
    _rising_ids.clear()
    _rising_ids.update(v.video_id for v in rising)

    payload = [_video_json(v) for v in videos]
    return {
        "videos": payload,
        "rising_count": len(rising),
        "off_topic_count": sum(1 for v in payload if not v["on_topic"]),
        "errors": errors,
    }


@app.post("/api/videos/rising")
def find_rising_videos():
    """가점 항목: '연애' 키워드로 뜨기 직전 영상 찾기 (유튜브 전체 검색, 초안까지만)."""
    found = discover_rising(
        min_views=settings.rising_min_views,
        max_views=settings.rising_max_views,
        min_views_per_hour=settings.rising_min_vph,
        api_key=settings.youtube_api_key,
        profile=_comment_reader_profile(),
    )
    if found.error:
        raise HTTPException(status_code=502, detail=f"검색 실패: {found.error}")

    for v in found.rising:
        if v.video_id not in _videos:          # 채널 목록에 이미 있으면 게시 가능 상태 유지
            _draft_only.add(v.video_id)
            _videos[v.video_id] = v
        _rising_ids.add(v.video_id)

    return {
        "videos": [_video_json(v) for v in found.rising],
        "keyword": found.keyword,
        "hours": found.hours,
        "searched": found.searched,
    }


class LinkIn(BaseModel):
    url: str


@app.post("/api/videos/by-link")
def video_by_link(body: LinkIn):
    """가점 항목: 링크 직접 입력."""
    try:
        video_id = extract_video_id(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if video_id in _videos:
        return {"video": _video_json(_videos[video_id])}

    # RSS 에 없는 영상이다. 공식 oEmbed 로 제목·채널·썸네일만 채운다 (키 불필요).
    meta = fetch_oembed(video_id)
    topic = _topic_of(video_id, meta.get("title", ""))
    stub = {
        "topic_score": topic.score,
        "topic_label": topic.label,
        # 링크로 직접 넣은 영상은 사용자가 의도적으로 고른 것이므로 숨기지 않는다
        "on_topic": True,
        "video_id": video_id,
        "title": meta.get("title") or "(제목을 가져오지 못한 영상)",
        "channel": meta.get("channel", ""),
        "published": None,
        "thumbnail": meta.get("thumbnail") or f"https://i3.ytimg.com/vi/{video_id}/hqdefault.jpg",
        "views": 0,
        "views_per_hour": 0,
        "age_hours": 0,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "rising": False,
        "commented": video_id in activity.posted_video_ids(),
    }
    _link_videos[video_id] = stub
    return {"video": stub}


# --- 2. 분석 · 초안 ---

@app.get("/api/analyze/{video_id}")
def analyze(video_id: str, title: str = "", channel: str = ""):
    video = _videos.get(video_id)
    description = ""
    if video:
        title = title or video.title
        channel = channel or video.channel
        description = video.description
    elif video_id in _link_videos:
        stub = _link_videos[video_id]
        title = title or stub["title"]
        channel = channel or stub["channel"]

    if not title:
        # 목록을 거치지 않고 분석만 호출한 경우 (서버 재시작 직후 등).
        # 제목 없이 분석하면 품질이 크게 떨어지므로 공식 oEmbed 로 채운다.
        meta = fetch_oembed(video_id)
        title = meta.get("title", "")
        channel = channel or meta.get("channel", "")

    transcript = fetch_transcript(video_id)
    top = fetch_top_comments(
        video_id, api_key=settings.youtube_api_key, profile=_comment_reader_profile()
    )

    provider = settings.effective_provider
    video_url = (f"https://www.youtube.com/watch?v={video_id}"
                 if settings.gemini_watch_video else "")
    try:
        analysis = get_analyzer(provider, settings).analyze(
            title=title, channel=channel, transcript=transcript,
            description=description, top_comments=top.texts, brand=settings.brand,
            video_url=video_url,
        )
    except Exception as e:
        # AI 가 실패해도 화면은 계속 돌아가야 한다 (할당량 초과·네트워크 등).
        # 다만 그때 들어가는 초안은 틀에 박힌 임시 문구라 게시는 막는다 (_validate_text).
        ai_error = _explain_ai_failure(e)
        analysis = get_analyzer("demo").analyze(
            title=title, channel=channel, transcript=transcript,
            description=description, top_comments=top.texts, brand=settings.brand,
        )
        analysis.notes.insert(0, f"{provider} 호출이 실패해 데모로 대체했습니다: {str(e)[:120]}")
    else:
        ai_error = None
    check = _validate_text(analysis.draft)
    return {
        "ai_error": ai_error,
        "draft_is_placeholder": is_placeholder_draft(analysis.draft, settings.brand),
        "concern": analysis.concern,
        "quote": analysis.quote,
        "quote_timestamp": analysis.quote_timestamp,
        "quote_source": analysis.quote_source,
        "watched_video": analysis.watched_video,
        "draft": analysis.draft,
        "source": analysis.source,
        "is_demo": analysis.is_demo,
        "notes": analysis.notes,
        "transcript": {
            "available": transcript.available,
            "language": transcript.language,
            "is_generated": transcript.is_generated,
            "snippets": len(transcript.snippets),
            "error": transcript.error,
            "lines": [
                {"t": sn.timestamp, "text": sn.text}
                for sn in transcript.snippets[:60]
            ],
        },
        "top_comments": {
            "items": [{"text": c.text, "likes": c.likes} for c in top.items],
            "error": top.error,
        },
        "validation": {"ok": check.ok, "errors": check.errors, "warnings": check.warnings},
    }


class DraftIn(BaseModel):
    text: str


@app.post("/api/validate")
def validate(body: DraftIn):
    check = _validate_text(body.text)
    return {
        "ok": check.ok,
        "errors": check.errors,
        "warnings": check.warnings,
        "length": len(body.text.strip()),
    }


# --- 3. 댓글 달기 ---

class OpenIn(BaseModel):
    video_id: str
    video_title: str = ""
    profile: str = ""
    text: str = ""


@app.post("/api/open")
def open_video(body: OpenIn):
    """전용 크롬 프로필 창으로 영상을 연다 (API 게시 방식의 첫 단계)."""
    profile = _resolve_profile(body.profile, "api")
    url = f"https://www.youtube.com/watch?v={body.video_id}&hl=ko"  # 한국어 화면
    try:
        open_in_profile(settings.profiles_dir / profile, url, settings.chrome_path)
    except BrowserError as e:
        _record_failure(body.video_id, body.video_title, profile, body.text,
                        f"프로필 열기 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    return {"opened": url, "profile": profile}


class PostIn(BaseModel):
    video_id: str
    video_title: str = ""
    profile: str = ""
    text: str


def _precheck(body: "PostIn") -> list[str]:
    """두 게시 방식 공통. 규칙을 어기면 HTTPException, 통과하면 경고 목록."""
    if body.video_id in _draft_only:
        raise HTTPException(
            status_code=409,
            detail="키워드 검색으로 찾은 영상은 초안까지만 만듭니다 (과제 기준).",
        )
    # 1) 운영 규칙 — 영상당 1개 · 하루 상한
    gate = activity.gate(settings.daily_max_comments)
    allowed = gate.check(body.video_id)
    if not allowed.ok:
        raise HTTPException(status_code=409, detail=" / ".join(allowed.errors))

    # 2) 댓글 내용 규칙 — 길이 · 링크 · 해시태그 · 후기 · 광고 표기
    check = _validate_text(body.text)
    if not check.ok:
        raise HTTPException(status_code=400, detail=" / ".join(check.errors))
    return allowed.warnings + check.warnings


@app.post("/api/post")
def post(body: PostIn):
    """운영 규칙을 통과한 댓글을 공식 API 로 게시하고, 확인하고, 기록한다."""
    warnings = _precheck(body)
    profile = _resolve_profile(body.profile, "api")

    # 3) 게시 + 확인
    try:
        result = post_and_verify(profile, body.video_id, body.text)
    except Exception as e:
        # PostError 뿐 아니라 인증 만료(RefreshError)·토큰 없음(AuthError)도
        # 실패로 기록한다. 안 그러면 기록 없이 500 으로 끝난다.
        reason = str(e) if isinstance(e, PostError) else _explain_unexpected(e)
        _record_failure(body.video_id, body.video_title, profile, body.text, reason,
                        method="api")
        raise HTTPException(status_code=502, detail=reason)

    # 4) 기록
    activity.append(Record(
        video_id=body.video_id, video_title=body.video_title, profile=profile,
        comment=body.text, status="posted", method="api",
    ))
    gate = activity.gate(settings.daily_max_comments)

    return {
        "comment_id": result.comment_id,
        "comment_url": result.url,
        "profile": profile,
        "verified": result.verified,
        "channel": result.channel_title,
        "posted_today": gate.posted_today,
        "remaining": gate.remaining,
        "warnings": warnings,
    }


# --- 3-b. 브라우저에서 한 글자씩 타이핑해 게시 ---
#
# 타이핑은 수십 초 걸리므로 작업을 백그라운드로 돌리고, 화면은 진행 단계를 받아 간다.
# 같은 프로필 폴더를 두 브라우저가 동시에 열 수 없으므로 한 번에 하나만 돈다.

_jobs: dict[str, dict] = {}
_post_lock = threading.Lock()


def _lookup_by_api(profile: str, video_id: str, text: str) -> str:
    """API 로 방금 댓글을 찾는다. 반영이 늦을 수 있어 한 번 더 본다. 토큰이 없으면 ""."""
    if not token_path(profile).exists():
        return ""
    for attempt in range(2):
        try:
            found = find_my_comment(profile, video_id, text)
        except Exception:
            return ""
        if found:
            return found
        if attempt == 0:
            time.sleep(4)
    return ""


def _run_typing(job_id: str, profile: str, body: "PostIn", warnings: list[str]) -> None:
    job = _jobs[job_id]

    def step(name: str) -> None:
        job["step"] = name

    def failed(message: str, shot: str | None) -> None:
        rec = _record_failure(body.video_id, body.video_title, profile, body.text,
                              message, screenshot=shot, method="typing")
        job.update(status="failed", error=message,
                   screenshot=f"/api/screenshots/{rec.screenshot}" if rec.screenshot else None)

    try:
        seen_on_page = True
        try:
            r = post_by_typing(
                settings.profiles_dir / profile, body.video_id, body.text,
                chrome_path=settings.chrome_path,
                screenshot_dir=settings.screenshot_dir,
                on_step=step,
            )
            page_comment_id = r.comment_id
        except TypingPostError as e:
            if not e.submitted:
                failed(str(e), e.screenshot)
                return
            # 게시 버튼은 눌렀다. 실제로 달렸는지 API 로 확인한다.
            page_comment_id = _lookup_by_api(profile, body.video_id, body.text)
            if not page_comment_id:
                failed(f"{e} — 게시됐는지 확인되지 않았습니다. 유튜브에서 직접 확인하세요.",
                       e.screenshot)
                return
            seen_on_page = False
            warnings = warnings + [f"화면 확인은 실패했지만 API 로 게시를 확인했습니다 ({e})"]
        except Exception as e:
            failed(_explain_unexpected(e), None)
            return

        # 공개됐는지 API 로 대조한다 (토큰이 있을 때).
        # 작성자 본인 화면에는 유튜브가 숨긴(스팸·검토 대기) 댓글도 잠깐 보이므로,
        # 화면에서 봤다는 것만으로는 '확인됨'이 아니다 (실제로 겪음).
        has_token = token_path(profile).exists()
        api_comment_id = _lookup_by_api(profile, body.video_id, body.text)
        if has_token and not api_comment_id:
            warnings = warnings + [
                "화면에는 보였지만 공개 댓글로 조회되지 않습니다. 유튜브가 검토 대기·스팸으로 "
                "숨겼거나, 브라우저 로그인 계정이 다를 수 있습니다."
            ]
        comment_id = api_comment_id or page_comment_id

        activity.append(Record(
            video_id=body.video_id, video_title=body.video_title, profile=profile,
            comment=body.text, status="posted", method="typing",
        ))
        gate = activity.gate(settings.daily_max_comments)
        url = (f"https://www.youtube.com/watch?v={body.video_id}&lc={comment_id}&hl=ko"
               if comment_id else f"https://www.youtube.com/watch?v={body.video_id}&hl=ko")
        job.update(
            status="done", step="done",
            result={
                "comment_id": comment_id,
                "comment_url": url,
                "profile": profile,
                "verified": bool(api_comment_id) if has_token else seen_on_page,
                "seen_on_page": seen_on_page,
                "verified_by_api": bool(api_comment_id),
                "posted_today": gate.posted_today,
                "remaining": gate.remaining,
                "warnings": warnings,
            },
        )
    finally:
        _post_lock.release()


@app.post("/api/post-typing")
def post_typing(body: PostIn):
    """프로필 창을 열어 한 글자씩 타이핑해 게시한다. 진행은 /api/jobs/{id} 로 본다."""
    warnings = _precheck(body)
    profile = _resolve_profile(body.profile, "typing")
    if not _post_lock.acquire(blocking=False):
        raise HTTPException(status_code=409,
                            detail="다른 댓글을 게시하는 중입니다. 끝난 뒤 다시 시도하세요.")
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "running", "step": "open", "profile": profile}
    try:
        threading.Thread(
            target=_run_typing, args=(job_id, profile, body, warnings), daemon=True
        ).start()
    except Exception:
        _post_lock.release()
        raise
    return {"job_id": job_id, "profile": profile}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    return job


class ConfirmIn(BaseModel):
    comment_url: str
    profile: str = ""


@app.post("/api/confirm")
def confirm(body: ConfirmIn):
    """게시된 댓글을 프로필 창에서 열어 눈으로 확인한다.

    과제 요구: "게시 → 내 댓글이 보이는지 확인까지 화면에 보이게".
    """
    profile = body.profile or settings.profiles[0]
    try:
        open_in_profile(settings.profiles_dir / profile, body.comment_url, settings.chrome_path)
    except BrowserError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"opened": body.comment_url, "profile": profile}


# --- 기록 ---

class RecordIn(BaseModel):
    video_id: str
    video_title: str = ""
    profile: str = ""
    comment: str = ""
    status: str = "posted"
    error: str | None = None


@app.post("/api/log")
def add_log(body: RecordIn):
    if body.status not in ("posted", "failed", "draft", "skipped"):
        raise HTTPException(status_code=400, detail=f"알 수 없는 상태: {body.status}")
    activity.append(Record(**body.model_dump()))
    gate = activity.gate(settings.daily_max_comments)
    return {"posted_today": gate.posted_today, "remaining": gate.remaining}


@app.get("/api/log")
def get_log(limit: int = 50):
    return {
        "records": [
            {
                "ts": r.ts,
                "time": r.local_time,
                "video_id": r.video_id,
                "video_title": r.video_title,
                "profile": r.profile,
                "comment": r.comment,
                "status": r.status,
                "error": r.error,
                "screenshot": f"/api/screenshots/{r.screenshot}" if r.screenshot else None,
                "method": r.method,
            }
            for r in activity.recent(limit)
        ]
    }


@app.get("/api/screenshots/{name}")
def get_screenshot(name: str):
    """실패 기록에 붙은 화면 캡처."""
    path = (settings.screenshot_dir / name).resolve()
    if path.parent != settings.screenshot_dir.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="캡처를 찾을 수 없습니다")
    return FileResponse(path, media_type="image/png")


# --- 정적 파일 ---

@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def main() -> None:
    import uvicorn

    print("대시보드: http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
