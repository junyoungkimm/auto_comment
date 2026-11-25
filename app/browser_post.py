"""크롬 프로필 창에서 한 글자씩 타이핑해 댓글을 단다.

과제 요구: "[댓글 달기]를 누르면 프로필이 열리고, 선택한 영상에서
댓글 창 → 한 글자씩 타이핑 → 게시 → 내 댓글이 보이는지 확인까지 화면에 보이게".

Playwright launch_persistent_context 로 전용 프로필 폴더(--user-data-dir)를 연다.
프로필은 미리 일반 크롬으로 로그인해 둔 상태여야 한다
(구글은 자동 제어 브라우저 안에서의 '로그인'을 막지만, 이미 로그인된 세션은 그대로 쓴다).

하지 않는 것: 자동화 흔적 숨기기, 무작위 타이핑 속도 같은 감지 우회.
고정된 속도로 화면에 보이게 치는 것까지만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

TYPING_DELAY_MS = 70          # 고정 속도. 120자면 약 8초
SHOW_RESULT_SECONDS = 5       # 게시 후 내 댓글을 화면에 보여주는 시간
WATCH_URL = "https://www.youtube.com/watch?v={video_id}&hl=ko"
COMMENT_URL = "https://www.youtube.com/watch?v={video_id}&lc={comment_id}&hl=ko"

# 유튜브 댓글 입력부 (한국어 화면 기준으로 확인함)
SEL_AVATAR = "button#avatar-btn"
SEL_PLACEHOLDER = "#simplebox-placeholder"
SEL_EDITOR = "ytd-commentbox #contenteditable-root"
SEL_SUBMIT = "ytd-commentbox #submit-button button, ytd-commentbox #submit-button"
SEL_THREAD = "ytd-comment-thread-renderer"


class TypingPostError(RuntimeError):
    """타이핑 게시 실패. screenshot 은 실패 순간의 브라우저 화면 파일 이름."""

    def __init__(self, message: str, screenshot: str | None = None,
                 submitted: bool = False) -> None:
        super().__init__(message)
        self.screenshot = screenshot
        # 게시 버튼을 누른 뒤에 실패했으면 댓글이 실제로 달렸을 수 있다
        self.submitted = submitted


@dataclass
class TypingResult:
    video_id: str
    comment_id: str   # 화면에서 못 읽으면 빈 문자열
    seen_on_page: bool
    dry_run_ready: bool | None = None   # 점검 모드에서 [댓글] 버튼이 눌릴 수 있었는지

    @property
    def url(self) -> str:
        if self.comment_id:
            return COMMENT_URL.format(video_id=self.video_id, comment_id=self.comment_id)
        return WATCH_URL.format(video_id=self.video_id)


Step = Callable[[str], None]


def _launch(pw, profile_dir: Path, chrome_path: str):
    kwargs = dict(
        user_data_dir=str(profile_dir),
        headless=False,
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        viewport={"width": 1280, "height": 860},
        args=["--no-first-run", "--no-default-browser-check", "--lang=ko"],
    )
    if chrome_path:
        kwargs["executable_path"] = chrome_path
    else:
        kwargs["channel"] = "chrome"
    return pw.chromium.launch_persistent_context(**kwargs)


def _explain_launch_error(e: Exception) -> str:
    text = str(e)
    # 같은 프로필 폴더를 쓰는 크롬이 이미 떠 있으면, 새로 띄운 크롬이 그쪽에 창을 넘기고
    # 바로 종료한다. 그래서 오류가 'in use' 대신 TargetClosedError 로 오기도 한다 (녹화 중 겪음).
    lowered = text.lower()
    if ("user data directory is already in use" in lowered or "processsingleton" in lowered
            or type(e).__name__ == "TargetClosedError" or "has been closed" in lowered):
        return "이 계정의 크롬 창이 이미 열려 있습니다. 그 창을 닫고 다시 시도하세요."
    return f"크롬 프로필을 열지 못했습니다: {type(e).__name__}: {text[:160]}"


def _open_comment_box(page) -> None:
    """댓글 영역은 지연 로딩이라 조금씩 내리며 입력창을 기다린다."""
    ph = page.locator(SEL_PLACEHOLDER)
    for _ in range(10):
        if ph.count() > 0 and ph.first.is_visible():
            break
        page.mouse.wheel(0, 700)
        page.wait_for_timeout(1000)
    if ph.count() == 0:
        raise RuntimeError("댓글 입력창을 찾지 못했습니다 (댓글이 꺼진 영상이거나 화면 구조가 바뀜)")
    # 화면 가운데로. 맨 위로 붙으면 유튜브 머리글(고정)에 가려 클릭이 엉뚱한 데 맞는다
    ph.first.evaluate("el => el.scrollIntoView({block: 'center'})")
    page.wait_for_timeout(500)
    ph.first.click()
    page.locator(SEL_EDITOR).first.wait_for(state="visible", timeout=10000)


def _normalize(s: str) -> str:
    return " ".join((s or "").split())


def _type_into_editor(page, text: str, delay_ms: int):
    """댓글 입력칸에 한 글자씩 넣고, 실제로 들어갔는지 확인한다.

    예전엔 입력칸을 좌표로 다시 클릭한 뒤 페이지 전체에 키를 보냈다. 그 클릭이
    고정 머리글 등에 맞으면 입력칸이 포커스를 잃고 빈 채로 접혀, 게시 버튼이 사라졌다
    (녹화 리허설에서 실제로 겪음). 이제 입력칸 요소에 직접 넣는다.
    """
    editor = page.locator(SEL_EDITOR).first
    want = _normalize(text)
    # 입력칸이 막 열린 직전에는 첫 글자 몇 개가 사라지는 일이 있다 (리허설에서 겪음).
    # 잠깐 기다렸다 입력하고, 그래도 어긋나면 지우고 한 번 더 친다.
    page.wait_for_timeout(1000)
    for attempt in range(2):
        editor.focus()
        editor.press_sequentially(text, delay=delay_ms)
        page.wait_for_timeout(600)
        if _normalize(editor.inner_text()) == want:
            return editor
        editor.focus()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.wait_for_timeout(800)
    raise RuntimeError("입력한 글이 댓글 창에 그대로 들어가지 않았습니다 (게시하지 않음)")


def _active_submit(page):
    """지금 열려 있는 댓글 창의 [댓글] 버튼. 숨은 답글 입력칸의 버튼은 건너뛴다."""
    boxes = page.locator("ytd-commentbox")
    for i in range(boxes.count()):
        box = boxes.nth(i)
        if box.locator("#contenteditable-root").first.is_visible():
            btn = box.locator("#submit-button button")
            return btn.first if btn.count() else box.locator("#submit-button").first
    return page.locator(SEL_SUBMIT).first


def _find_my_comment(page, text: str):
    """방금 단 댓글 스레드를 찾는다. 유튜브가 줄바꿈·공백을 정리하므로 앞부분으로 찾는다."""
    probe = " ".join(text.split())[:20]
    return page.locator(SEL_THREAD).filter(has_text=probe).first


def _comment_id_from(thread) -> str:
    """스레드의 게시 시각 링크(…&lc=<id>)에서 댓글 ID를 읽는다."""
    try:
        href = thread.locator("#published-time-text a").first.get_attribute("href") or ""
    except Exception:
        return ""
    for part in href.replace("?", "&").split("&"):
        if part.startswith("lc="):
            return part[3:]
    return ""


def post_by_typing(
    profile_dir: Path,
    video_id: str,
    text: str,
    *,
    chrome_path: str = "",
    screenshot_dir: Path | None = None,
    on_step: Step = lambda s: None,
    typing_delay_ms: int = TYPING_DELAY_MS,
    dry_run: bool = False,
) -> TypingResult:
    """프로필 창을 열어 한 글자씩 입력하고 게시한 뒤, 화면에서 내 댓글을 확인한다.

    호출 전에 운영 규칙(길이·금지어·영상당 1개·하루 상한)을 통과시켜야 한다.
    dry_run=True 면 [댓글] 버튼을 누르기 직전에 멈추고 입력을 지운다 (게시 안 함).
    """
    from playwright.sync_api import sync_playwright

    if not text.strip():
        raise TypingPostError("빈 댓글은 게시할 수 없습니다.")

    on_step("open")
    with sync_playwright() as pw:
        try:
            ctx = _launch(pw, profile_dir, chrome_path)
        except Exception as e:
            raise TypingPostError(_explain_launch_error(e)) from e

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        submitted = False

        def fail(message: str) -> TypingPostError:
            shot = None
            if screenshot_dir is not None:
                try:
                    from app.capture import screenshot_name

                    screenshot_dir.mkdir(parents=True, exist_ok=True)
                    shot = screenshot_name(video_id)
                    page.screenshot(path=str(screenshot_dir / shot), full_page=False)
                except Exception:
                    shot = None
            return TypingPostError(message, screenshot=shot, submitted=submitted)

        try:
            try:
                page.goto(WATCH_URL.format(video_id=video_id),
                          wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
            except Exception as e:
                raise fail(f"영상을 열지 못했습니다: {type(e).__name__}") from e

            if page.locator(SEL_AVATAR).count() == 0:
                raise fail("이 프로필이 유튜브에 로그인돼 있지 않습니다. "
                           "scripts/setup_profile.py 로 먼저 로그인하세요.")

            # 댓글 창 → 한 글자씩 타이핑
            try:
                _open_comment_box(page)
            except Exception as e:
                raise fail(str(e)) from e

            on_step("typing")
            try:
                _type_into_editor(page, text, typing_delay_ms)
            except Exception as e:
                raise fail(str(e) if isinstance(e, RuntimeError)
                           else f"댓글 입력 실패: {type(e).__name__}") from e

            # 게시
            on_step("submit")
            submit = _active_submit(page)
            try:
                submit.wait_for(state="visible", timeout=5000)
                if dry_run:
                    # 점검 모드: 버튼이 눌릴 수 있는 상태인지까지만 보고, 입력을 지우고 닫는다
                    ready = submit.is_enabled()
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Delete")
                    return TypingResult(video_id=video_id, comment_id="",
                                        seen_on_page=False, dry_run_ready=ready)
                submit.click()
                submitted = True
            except Exception as e:
                raise fail(f"게시 버튼을 누르지 못했습니다: {type(e).__name__}") from e

            # 내 댓글이 보이는지 확인
            on_step("verify")
            thread = _find_my_comment(page, text)
            try:
                thread.wait_for(state="visible", timeout=15000)
            except Exception as e:
                raise fail("게시 후 화면에서 내 댓글을 찾지 못했습니다 "
                           "(유튜브가 검토 대기로 돌렸을 수 있습니다)") from e

            thread.scroll_into_view_if_needed()
            comment_id = _comment_id_from(thread)
            page.wait_for_timeout(SHOW_RESULT_SECONDS * 1000)  # 시연 화면에 보이도록
            return TypingResult(video_id=video_id, comment_id=comment_id, seen_on_page=True)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
