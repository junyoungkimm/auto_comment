"""환경 변수 -> Settings. 모든 값에 기본값이 있고 키만 필수다."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    youtube_api_key: str = ""

    channels: tuple[str, ...] = ()   # @핸들 또는 UC... 채널 ID

    # AI: 키가 없으면 자동으로 demo 로 떨어진다
    ai_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    # 주 모델이 과부하(503)거나 응답이 없을 때 쓸 대체 모델
    # 쉼표로 여러 개. 앞에서부터 차례로 시도한다
    gemini_fallback_model: str = "gemini-2.5-flash,gemini-3.5-flash-lite"
    # 자막을 못 받으면 제미나이가 유튜브 영상을 직접 보게 한다
    gemini_watch_video: bool = True

    min_chars: int = 40
    max_chars: int = 120
    daily_max_comments: int = 10
    rising_min_views: int = 1000
    rising_max_views: int = 5000
    rising_min_vph: float = 150.0
    brand: str = "운명원"
    # 홍보 댓글임을 드러내는 문구를 필수로 할지 (표시광고법)
    require_disclosure: bool = True

    profiles: tuple[str, ...] = ("계정1", "계정2", "계정3")
    chrome_path: str = ""

    profiles_dir: Path = PROJECT_ROOT / "profiles"
    data_dir: Path = PROJECT_ROOT / "data"

    @property
    def effective_provider(self) -> str:
        """키가 없으면 demo 로 내려간다. 키 없이도 화면을 볼 수 있게."""
        if self.ai_provider == "gemini" and not self.gemini_api_key:
            return "demo"
        return self.ai_provider

    @property
    def log_path(self) -> Path:
        return self.data_dir / "activity.jsonl"

    @property
    def screenshot_dir(self) -> Path:
        return self.data_dir / "screenshots"


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    return default if not raw or not raw.strip() else int(raw)


def _env_str(key: str, default: str) -> str:
    raw = os.getenv(key)
    return default if raw is None or not raw.strip() else raw.strip()


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    channels_raw = _env_str("AGENT_CHANNELS", "")
    channels = tuple(c.strip() for c in channels_raw.split(",") if c.strip())
    profiles_raw = _env_str("AGENT_PROFILES", ",".join(Settings.profiles))
    profiles = tuple(p.strip() for p in profiles_raw.split(",") if p.strip())
    return Settings(
        youtube_api_key=_env_str("YOUTUBE_API_KEY", ""),
        channels=channels,
        ai_provider=_env_str("AGENT_AI_PROVIDER", Settings.ai_provider).lower(),
        gemini_api_key=_env_str("GEMINI_API_KEY", ""),
        gemini_model=_env_str("AGENT_GEMINI_MODEL", Settings.gemini_model),
        gemini_fallback_model=_env_str(
            "AGENT_GEMINI_FALLBACK", Settings.gemini_fallback_model
        ),
        gemini_watch_video=_env_bool("AGENT_GEMINI_WATCH_VIDEO", Settings.gemini_watch_video),
        min_chars=_env_int("AGENT_MIN_CHARS", Settings.min_chars),
        max_chars=_env_int("AGENT_MAX_CHARS", Settings.max_chars),
        daily_max_comments=_env_int(
            "AGENT_DAILY_MAX_COMMENTS", Settings.daily_max_comments
        ),
        rising_min_views=_env_int("AGENT_RISING_MIN_VIEWS", Settings.rising_min_views),
        rising_max_views=_env_int("AGENT_RISING_MAX_VIEWS", Settings.rising_max_views),
        rising_min_vph=float(_env_int("AGENT_RISING_MIN_VPH", int(Settings.rising_min_vph))),
        brand=_env_str("AGENT_BRAND", Settings.brand),
        require_disclosure=_env_bool(
            "AGENT_REQUIRE_DISCLOSURE", Settings.require_disclosure
        ),
        profiles=profiles or Settings.profiles,
        chrome_path=_env_str("AGENT_CHROME_PATH", ""),
        # 기록·캡처 위치. 시연·테스트용 기록을 실제 기록과 분리할 때 쓴다
        data_dir=Path(_env_str("AGENT_DATA_DIR", str(Settings.data_dir))),
    )
