"""전용 크롬 프로필 창을 연다.

연결 방식:
  프로필 폴더를 지정해 연다 (Playwright launchPersistentContext 또는 --user-data-dir).

여기서는 --user-data-dir 쪽을 쓴다. 게시는 공식 API 가 하고 이 창은 화면 확인용이라
DOM 조작이 필요 없어서, 브라우저 수명 관리가 없는 쪽이 훨씬 안정적이다.
(DOM 접근이 필요한 준비·점검은 scripts/setup_profile.py 가 Playwright 로 한다)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


class BrowserError(RuntimeError):
    pass


def find_chrome(explicit: str = "") -> str:
    if explicit:
        if not Path(explicit).exists():
            raise BrowserError(f"지정한 크롬 경로가 없습니다: {explicit}")
        return explicit
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    import os

    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"
    if local.exists():
        return str(local)
    raise BrowserError(
        "크롬을 찾지 못했습니다. .env 의 AGENT_CHROME_PATH 에 경로를 지정해 주세요."
    )


def open_in_profile(
    profile_dir: Path, url: str, chrome_path: str = "", new_window: bool = False
) -> None:
    """지정한 프로필 폴더로 크롬을 열고 url 로 이동한다.

    같은 프로필이 이미 떠 있으면 그 창에 새 탭으로 열린다.
    """
    chrome = find_chrome(chrome_path)
    profile_dir.mkdir(parents=True, exist_ok=True)

    args = [chrome, f"--user-data-dir={profile_dir}", "--no-first-run",
            "--no-default-browser-check", "--lang=ko"]
    if new_window:
        args.append("--new-window")
    args.append(url)

    try:
        subprocess.Popen(args, close_fds=True)
    except OSError as e:
        raise BrowserError(f"크롬 실행 실패: {e}") from e
