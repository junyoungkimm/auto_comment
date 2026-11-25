"""유튜브 공식 API로 댓글을 게시하고, 실제로 달렸는지 확인한다.

브라우저를 조종하지 않는다. commentThreads.insert 는 유튜브가 댓글 게시를 위해
공식 제공하는 엔드포인트다.

할당량: insert 약 52유닛, 확인 조회 약 1유닛. 하루 한도 10,000유닛.
"""

from __future__ import annotations

from dataclasses import dataclass

from googleapiclient.errors import HttpError

from app.google_auth import build_service, whoami

WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
# hl=ko: 유튜브 한국어 화면에서 작동하도록. 계정 언어 설정과 무관하게 한국어로 연다.
COMMENT_URL = "https://www.youtube.com/watch?v={video_id}&lc={comment_id}&hl=ko"


class PostError(RuntimeError):
    """게시 실패. message 는 사람이 읽을 수 있는 설명."""


@dataclass
class PostResult:
    comment_id: str
    video_id: str
    channel_id: str
    channel_title: str
    text: str
    verified: bool = False

    @property
    def url(self) -> str:
        """그 댓글로 바로 가는 주소. 확인 단계에서 이 주소를 연다."""
        return COMMENT_URL.format(video_id=self.video_id, comment_id=self.comment_id)


def _explain(error: HttpError) -> str:
    """구글 오류를 사람이 읽을 수 있는 말로 바꾼다."""
    status = getattr(error.resp, "status", None)
    detail = ""
    try:
        detail = error.error_details[0].get("reason", "")  # type: ignore[attr-defined]
    except Exception:
        detail = ""

    known = {
        "commentsDisabled": "이 영상은 댓글이 꺼져 있습니다.",
        "forbidden": "이 영상에 댓글을 달 권한이 없습니다.",
        "quotaExceeded": "오늘 API 할당량을 모두 썼습니다. 내일 다시 시도하세요.",
        "rateLimitExceeded": "요청이 너무 빠릅니다. 잠시 후 다시 시도하세요.",
        "videoNotFound": "영상을 찾을 수 없습니다 (비공개이거나 삭제됨).",
        "ineligibleAccount": "이 계정으로는 댓글을 달 수 없습니다. 유튜브 채널이 있는지 확인하세요.",
    }
    if detail in known:
        return known[detail]
    if status == 401:
        return "인증이 만료됐습니다. scripts/auth_youtube.py 를 다시 실행하세요."
    if status == 403:
        return f"권한 거부 ({detail or '사유 불명'})"
    return f"HTTP {status} {detail}".strip()


def post_comment(profile: str, video_id: str, text: str) -> PostResult:
    """영상에 댓글을 하나 단다.

    호출 전에 운영 규칙(길이·금지어·영상당 1개·하루 상한)을 통과시켜야 한다.
    이 함수는 규칙을 검사하지 않는다 — 호출부의 책임이다.
    """
    if not text.strip():
        raise PostError("빈 댓글은 게시할 수 없습니다.")

    service = build_service(profile)
    me = whoami(service)

    body = {
        "snippet": {
            "videoId": video_id,
            "topLevelComment": {"snippet": {"textOriginal": text}},
        }
    }
    try:
        response = service.commentThreads().insert(part="snippet", body=body).execute()
    except HttpError as e:
        raise PostError(_explain(e)) from e

    comment_id = response.get("id", "")
    if not comment_id:
        raise PostError("게시는 됐지만 댓글 ID를 받지 못했습니다.")

    return PostResult(
        comment_id=comment_id,
        video_id=video_id,
        channel_id=me["channel_id"],
        channel_title=me["title"],
        text=text,
    )


def verify_comment(profile: str, comment_id: str) -> bool:
    """게시된 댓글이 실제로 조회되는지 확인한다.

    "내 댓글이 보이는지 확인" 단계를 코드로 수행한다.
    """
    service = build_service(profile)
    try:
        response = (
            service.commentThreads().list(part="snippet", id=comment_id).execute()
        )
    except HttpError:
        return False
    return bool(response.get("items"))


def find_my_comment(profile: str, video_id: str, text: str) -> str:
    """이 프로필 계정이 그 영상에 단 댓글 중 text 와 같은 것의 ID. 없으면 "".

    브라우저 타이핑으로 게시한 뒤 두 가지를 확인하는 데 쓴다.
      - 실제로 달렸는지 (화면 확인이 실패했어도)
      - 브라우저 프로필 계정이 API 토큰 계정과 같은지
    """
    service = build_service(profile)
    me = whoami(service)
    want = " ".join(text.split())
    try:
        resp = service.commentThreads().list(
            part="snippet", videoId=video_id, order="time",
            maxResults=50, textFormat="plainText",
        ).execute()
    except HttpError as e:
        raise PostError(_explain(e)) from e
    for item in resp.get("items", []):
        top = item["snippet"]["topLevelComment"]
        sn = top["snippet"]
        if sn.get("authorChannelId", {}).get("value") != me["channel_id"]:
            continue
        if " ".join(sn.get("textOriginal", "").split()) == want:
            return top["id"]
    return ""


def post_and_verify(profile: str, video_id: str, text: str) -> PostResult:
    """게시하고 곧바로 확인까지 한다."""
    result = post_comment(profile, video_id, text)
    result.verified = verify_comment(profile, result.comment_id)
    return result
