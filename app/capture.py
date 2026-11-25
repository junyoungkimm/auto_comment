"""실패했을 때 화면을 캡처한다.

과제 요구: "실패하면 이유와 화면 캡처를 남깁니다".

프로필 창은 공식 API 게시와 별개로 --user-data-dir 로 띄운 일반 크롬이라
Playwright 로 그 탭만 찍을 수 없다. 대신 그 순간의 화면 전체를 찍는다
(대시보드의 오류 표시와 프로필 창이 같이 남는다).

추가 설치 없이 윈도우 기본 기능(PowerShell + System.Drawing)을 쓴다.
캡처가 실패해도 예외를 던지지 않는다 — 캡처 실패가 기록을 막으면 안 된다.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 모니터가 여러 대여도 전부 담도록 VirtualScreen 을 찍는다
PS_SCRIPT = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save($env:CAPTURE_PATH, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"""


def screenshot_name(video_id: str, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    safe_id = "".join(c for c in video_id if c.isalnum() or c in "-_")[:20] or "unknown"
    return f"fail-{stamp}-{safe_id}.png"


def capture_screen(out_dir: Path, video_id: str) -> str | None:
    """화면을 PNG 로 저장하고 파일 이름을 돌려준다. 실패하면 None."""
    if sys.platform != "win32":
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    name = screenshot_name(video_id)
    path = out_dir / name
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT],
            env={**_env(), "CAPTURE_PATH": str(path)},
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return name if path.exists() else None


def _env() -> dict:
    import os

    return dict(os.environ)
