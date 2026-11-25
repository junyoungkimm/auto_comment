# -*- coding: utf-8 -*-
"""YouTube Data API 인증 (계정별 1회).

    python scripts/auth_youtube.py              # 첫 번째 프로필
    python scripts/auth_youtube.py 계정2       # 다른 계정
    python scripts/auth_youtube.py --status     # 인증 상태만 확인
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.config import load_settings  # noqa: E402
from app.google_auth import (  # noqa: E402
    CLIENT_SECRET_PATH,
    AuthError,
    build_service,
    load_credentials,
    token_path,
    whoami,
)


def show_status(settings) -> int:
    print(f"client_secret.json : {'있음' if CLIENT_SECRET_PATH.exists() else '없음'}")
    print(f"  경로: {CLIENT_SECRET_PATH}\n")
    print("계정별 인증 상태:")
    for name in settings.profiles:
        path = token_path(name)
        if not path.exists():
            print(f"  - {name}: 인증 안 됨")
            continue
        try:
            creds = load_credentials(name)
            if creds is None:
                print(f"  - {name}: 토큰 있으나 만료 (재인증 필요)")
                continue
            info = whoami(build_service(name))
            print(f"  - {name}: OK  채널='{info['title']}'  id={info['channel_id']}")
        except Exception as e:
            print(f"  - {name}: 오류 {type(e).__name__}: {str(e)[:120]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="YouTube Data API 인증")
    parser.add_argument("profile", nargs="?", default=None)
    parser.add_argument("--status", action="store_true", help="인증 상태만 확인")
    args = parser.parse_args()

    settings = load_settings()

    if args.status:
        return show_status(settings)

    name = args.profile or settings.profiles[0]
    if name not in settings.profiles:
        print(f"[!] '{name}' 은 설정에 없습니다. 가능: {', '.join(settings.profiles)}")
        return 1

    if not CLIENT_SECRET_PATH.exists():
        print("[!] secrets/client_secret.json 이 없습니다.\n")
        print("  Google Cloud Console 에서 받아야 합니다:")
        print("   1) https://console.cloud.google.com 에서 프로젝트 생성")
        print("   2) API 및 서비스 > 라이브러리 > 'YouTube Data API v3' > 사용")
        print("   3) API 및 서비스 > OAuth 동의 화면 > 외부 > 앱 이름·이메일 입력")
        print("      -> 대상(테스트 사용자)에 본인 구글 계정을 반드시 추가")
        print("   4) 사용자 인증 정보 > 만들기 > OAuth 클라이언트 ID > 데스크톱 앱")
        print("   5) 받은 JSON 을 secrets/client_secret.json 으로 저장")
        return 1

    print(f"계정 '{name}' 인증을 시작합니다.")
    print("브라우저가 열리면 구글 계정으로 로그인하고 권한을 허용해 주세요.\n")
    try:
        service = build_service(name, interactive=True)
        info = whoami(service)
    except AuthError as e:
        print(f"[실패] {e}")
        return 1
    except Exception as e:
        print(f"[실패] {type(e).__name__}: {str(e)[:300]}")
        return 1

    print(f"\n[OK] 인증 완료")
    print(f"  채널    : {info['title']}")
    print(f"  채널 ID : {info['channel_id']}")
    print(f"  구독자  : {info['subscribers']}")
    print(f"  토큰    : {token_path(name)}  (git 제외됨)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
