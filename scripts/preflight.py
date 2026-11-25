# -*- coding: utf-8 -*-
"""시연 전 점검 — 실제로 댓글을 달지 않고 게시 조건만 확인한다.

녹화 도중에 권한·경로·할당량 문제로 멈추는 걸 막으려고 만들었다.

    python scripts/preflight.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.browser import find_chrome  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.feed import fetch_channels  # noqa: E402
from app.google_auth import build_service, token_path, whoami  # noqa: E402
from app.storage import ActivityLog  # noqa: E402
from app.topics import score_video  # noqa: E402
from app.transcript import CACHE_DIR  # noqa: E402

WRITE_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"


def line(ok: bool, label: str, detail: str = "") -> bool:
    mark = "OK  " if ok else "실패"
    print(f"[{mark}] {label:22s} {detail}")
    return ok


def main() -> int:
    settings = load_settings()
    profile = settings.profiles[0]
    ok = True

    print(f"프로필: {profile}\n")

    # 1) 게시 권한
    path = token_path(profile)
    if not path.exists():
        ok &= line(False, "인증 토큰", f"{path.name} 없음 — scripts/auth_youtube.py 실행")
    else:
        token = json.loads(path.read_text(encoding="utf-8"))
        scopes = token.get("scopes", [])
        ok &= line(WRITE_SCOPE in scopes, "쓰기 권한",
                   f"{[s.split('/')[-1] for s in scopes]}")
        ok &= line(bool(token.get("refresh_token")), "refresh_token",
                   "있음" if token.get("refresh_token") else "없음 — 재인증 필요")

    # 2) 댓글을 달 채널
    try:
        me = whoami(build_service(profile))
        ok &= line(True, "유튜브 채널", f"{me['title']} ({me['channel_id']})")
    except Exception as e:
        ok &= line(False, "유튜브 채널", f"{type(e).__name__}: {str(e)[:70]}")

    # 3) 크롬
    try:
        ok &= line(True, "크롬 실행 파일", find_chrome(settings.chrome_path))
    except Exception as e:
        ok &= line(False, "크롬 실행 파일", str(e)[:70])

    cookies = settings.profiles_dir / profile / "Default" / "Network" / "Cookies"
    line(cookies.exists(), "프로필 로그인",
         "세션 있음" if cookies.exists() else "로그인 흔적 없음 — setup_profile.py 실행")

    # 4) AI
    line(settings.effective_provider != "demo", "AI",
         f"{settings.effective_provider} / {settings.gemini_model}"
         if settings.effective_provider != "demo" else "데모 모드 (키 없음)")

    # 5) 오늘 남은 게시 수
    gate = ActivityLog(settings.log_path).gate(settings.daily_max_comments)
    ok &= line(gate.remaining > 0, "오늘 게시 가능",
               f"{gate.remaining}/{settings.daily_max_comments}개")

    # 6) 영상과 자막 캐시
    try:
        videos, errors = fetch_channels(list(settings.channels))
        on_topic = [v for v in videos if score_video(v.title).is_relevant]
        line(bool(on_topic), "영상 목록",
             f"{len(videos)}개 중 연애 {len(on_topic)}개, 채널 오류 {len(errors)}건")
    except Exception as e:
        line(False, "영상 목록", f"{type(e).__name__}: {str(e)[:60]}")

    cached = len(list(CACHE_DIR.glob("*.json"))) if CACHE_DIR.exists() else 0
    line(cached > 0, "자막 캐시",
         f"{cached}개" if cached else "비어 있음 — scripts/warmup.py 권장")

    print(f"\n종합: {'게시 준비 완료' if ok else '위 실패 항목을 먼저 해결하세요'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
