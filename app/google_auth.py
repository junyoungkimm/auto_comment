"""YouTube Data API OAuth 자격 증명 관리.

계정(프로필)마다 토큰 파일을 따로 둔다. 토큰은 secrets/ 아래에 저장되고
git 에는 올라가지 않는다.
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# 댓글 읽기 + 쓰기에 필요한 스코프 (commentThreads.insert 요구사항)
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = PROJECT_ROOT / "secrets"
CLIENT_SECRET_PATH = SECRETS_DIR / "client_secret.json"


class AuthError(RuntimeError):
    pass


def token_path(profile: str) -> Path:
    return SECRETS_DIR / f"token_{profile}.json"


def load_credentials(profile: str) -> Credentials | None:
    """저장된 토큰을 읽는다. 만료됐으면 갱신한다. 없으면 None."""
    path = token_path(profile)
    if not path.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json(), encoding="utf-8")
        return creds
    return None


def authorize(profile: str) -> Credentials:
    """브라우저를 열어 사용자 동의를 받고 토큰을 저장한다."""
    if not CLIENT_SECRET_PATH.exists():
        raise AuthError(
            f"{CLIENT_SECRET_PATH} 가 없습니다.\n"
            "  Google Cloud Console 에서 OAuth 클라이언트(데스크톱 앱)를 만들고\n"
            "  받은 JSON 을 client_secret.json 이름으로 secrets/ 에 넣어주세요."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    # access_type=offline + prompt=consent 로 refresh_token 을 확실히 받는다
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        authorization_prompt_message="브라우저에서 구글 계정 동의를 진행해 주세요...",
        success_message="인증 완료. 이 창을 닫고 터미널로 돌아가세요.",
    )
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    token_path(profile).write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_credentials(profile: str, interactive: bool = True) -> Credentials:
    """저장된 토큰을 쓰고, 없으면 (interactive 일 때) 인증을 시작한다."""
    creds = load_credentials(profile)
    if creds:
        return creds
    if not interactive:
        raise AuthError(
            f"'{profile}' 의 인증 토큰이 없습니다. "
            f"먼저 실행하세요: python scripts/auth_youtube.py {profile}"
        )
    return authorize(profile)


def build_service(profile: str, interactive: bool = False):
    """인증된 YouTube Data API 클라이언트를 만든다."""
    creds = get_credentials(profile, interactive=interactive)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def whoami(service) -> dict:
    """인증된 계정의 채널 정보를 돌려준다."""
    resp = (
        service.channels()
        .list(part="snippet,statistics", mine=True)
        .execute()
    )
    items = resp.get("items", [])
    if not items:
        raise AuthError(
            "이 구글 계정에 연결된 유튜브 채널이 없습니다.\n"
            "  댓글을 달려면 채널이 하나 있어야 합니다. "
            "youtube.com 에서 채널을 만든 뒤 다시 시도하세요."
        )
    item = items[0]
    return {
        "channel_id": item["id"],
        "title": item["snippet"]["title"],
        "subscribers": item.get("statistics", {}).get("subscriberCount", "?"),
    }
