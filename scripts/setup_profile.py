# -*- coding: utf-8 -*-
"""크롬 프로필을 열어 유튜브에 로그인해 두는 준비 스크립트.

이 프로필은 평소 쓰는 크롬(Default)과 완전히 분리되어 있고,
한 번 로그인해두면 다음 실행부터 로그인 상태로 열린다.

    python scripts/setup_profile.py              # 계정1 프로필
    python scripts/setup_profile.py 계정2       # 다른 프로필
    python scripts/setup_profile.py --check      # 로그인 상태만 확인하고 종료
    python scripts/setup_profile.py --list       # 만들어진 프로필 목록
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import load_settings  # noqa: E402

# 콘솔 인코딩 때문에 한글 출력이 죽지 않도록
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CHECK_VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
LOGIN_WAIT_SECONDS = 600  # 최대 10분 대기


def launch(pw, profile_dir: Path, chrome_path: str):
    kwargs = dict(
        user_data_dir=str(profile_dir),
        headless=False,
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        viewport={"width": 1280, "height": 900},
        args=["--no-first-run", "--no-default-browser-check"],
    )
    if chrome_path:
        kwargs["executable_path"] = chrome_path
    else:
        kwargs["channel"] = "chrome"  # 설치된 크롬을 그대로 쓴다
    return pw.chromium.launch_persistent_context(**kwargs)


def is_logged_in(page) -> bool:
    """우측 상단 아바타 버튼이 있으면 로그인된 상태."""
    try:
        return page.locator("button#avatar-btn").count() > 0
    except Exception:
        return False


def account_name(page) -> str:
    try:
        btn = page.locator("button#avatar-btn")
        if btn.count() == 0:
            return "?"
        img = btn.locator("img").first
        return img.get_attribute("alt") or "?"
    except Exception:
        return "?"


def check_comment_box(page, url: str = CHECK_VIDEO) -> tuple[bool, str]:
    """영상 페이지에서 댓글 입력창이 실제로 뜨는지 확인한다.

    유튜브 댓글 영역은 지연 로딩이라 한 번에 안 뜬다.
    조금씩 여러 번 내리면서 기다려야 한다.
    """
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)

    ph = page.locator("#simplebox-placeholder")
    for _ in range(6):
        page.mouse.wheel(0, 900)
        page.wait_for_timeout(1200)
        if ph.count() > 0:
            try:
                return True, ph.first.inner_text().strip()[:40]
            except Exception:
                return True, "(문구 읽기 실패)"
    return False, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="유튜브용 크롬 프로필 준비")
    parser.add_argument("profile", nargs="?", default=None, help="프로필 이름 (기본: 첫 번째)")
    parser.add_argument("--check", action="store_true", help="로그인 상태만 확인하고 종료")
    parser.add_argument("--list", action="store_true", help="만들어진 프로필 목록 출력")
    args = parser.parse_args()

    settings = load_settings()

    if args.list:
        print(f"설정된 프로필: {', '.join(settings.profiles)}")
        print(f"폴더: {settings.profiles_dir}")
        if settings.profiles_dir.exists():
            for d in sorted(settings.profiles_dir.iterdir()):
                if d.is_dir():
                    size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                    print(f"  - {d.name}  ({size/1024/1024:.0f} MB)")
        else:
            print("  (아직 만들어진 프로필 없음)")
        return 0

    name = args.profile or settings.profiles[0]
    if name not in settings.profiles:
        print(f"[!] '{name}' 은 설정에 없는 프로필입니다. 가능: {', '.join(settings.profiles)}")
        print("    .env 의 AGENT_PROFILES 에 추가하면 쓸 수 있습니다.")
        return 1

    profile_dir = settings.profiles_dir / name
    profile_dir.mkdir(parents=True, exist_ok=True)
    print(f"프로필: {name}")
    print(f"폴더  : {profile_dir}")
    print("평소 쓰는 크롬(Default)과는 분리된 별도 프로필입니다.\n")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            ctx = launch(pw, profile_dir, settings.chrome_path)
        except Exception as e:
            print(f"[실패] 크롬 실행 불가: {type(e).__name__}: {e}")
            print("  크롬이 설치되어 있는지 확인하거나, .env 의 AGENT_CHROME_PATH 에 경로를 지정하세요.")
            return 1

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto("https://www.youtube.com", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)

            if is_logged_in(page):
                print(f"[OK] 이미 로그인되어 있습니다 — 계정: {account_name(page)}")
            elif args.check:
                print("[--] 로그인되어 있지 않습니다.")
                print("     --check 없이 다시 실행하면 로그인할 시간을 드립니다.")
                ctx.close()
                return 2
            else:
                print("[--] 로그인되어 있지 않습니다.")
                print()
                print("  열린 크롬 창에서 직접 로그인해 주세요:")
                print("   1) 우측 상단 [로그인] 클릭")
                print("   2) 이 에이전트용으로 쓸 구글 계정으로 로그인")
                print("   3) 완료되면 이 창은 그대로 두세요 — 자동으로 감지합니다")
                print()
                print("  * 구글이 '이 브라우저 또는 앱은 안전하지 않을 수 있습니다'로 막으면")
                print("    여기서 중단하고 알려주세요. 설계를 바꿔야 합니다.")
                print()

                deadline = time.time() + LOGIN_WAIT_SECONDS
                while time.time() < deadline:
                    try:
                        if is_logged_in(page):
                            break
                        if page.is_closed():
                            print("[중단] 창이 닫혔습니다.")
                            return 1
                    except Exception:
                        print("[중단] 브라우저 연결이 끊겼습니다.")
                        return 1
                    remaining = int(deadline - time.time())
                    print(f"\r  로그인 대기 중... (남은 시간 {remaining//60}분 {remaining%60:02d}초)",
                          end="", flush=True)
                    time.sleep(3)
                print()

                if not is_logged_in(page):
                    print("[시간 초과] 로그인이 확인되지 않았습니다.")
                    ctx.close()
                    return 2
                print(f"[OK] 로그인 확인 — 계정: {account_name(page)}")

            # 로그인 상태에서 댓글 입력창이 실제로 뜨는지 확인
            print("\n댓글 입력창 확인 중...")
            found, text = check_comment_box(page)
            if found:
                print(f"[OK] 댓글 입력창 발견 — 문구: {text!r}")
                print("     ③ 댓글 달기 단계가 동작할 수 있는 상태입니다.")
            else:
                print("[!] 댓글 입력창을 찾지 못했습니다.")
                print("    해당 영상의 댓글이 꺼져 있거나, 화면 구조가 달라졌을 수 있습니다.")

            print("\n준비 완료. 이 프로필은 다음 실행부터 로그인 상태로 열립니다.")
            print("창을 닫습니다...")
            time.sleep(2)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
