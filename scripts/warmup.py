# -*- coding: utf-8 -*-
"""시연 전 준비 — 쓸 영상들의 자막을 미리 받아 캐시에 넣는다.

유튜브는 자막 요청이 몰리면 IP 를 일시 차단한다 (IpBlocked).
녹화 도중에 걸리면 분석이 멈추므로, 미리 천천히 받아둔다.
한 번 캐시되면 녹화 중에는 네트워크를 쓰지 않는다.

    python scripts/warmup.py              # 채널당 최신 3개
    python scripts/warmup.py --count 6    # 채널당 6개
    python scripts/warmup.py --status     # 캐시 현황만 확인
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.config import load_settings  # noqa: E402
from app.feed import fetch_channels  # noqa: E402
from app.transcript import CACHE_DIR, fetch_transcript, load_cached  # noqa: E402

PAUSE_SECONDS = 3.0  # fetch_transcript 자체 간격(1.5초)보다 넉넉하게


def show_status() -> int:
    if not CACHE_DIR.exists():
        print("캐시 없음. --status 없이 실행하면 받아옵니다.")
        return 0
    files = sorted(CACHE_DIR.glob("*.json"))
    size = sum(f.stat().st_size for f in files)
    print(f"캐시된 자막 {len(files)}개 ({size/1024:.0f} KB)")
    print(f"위치: {CACHE_DIR}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="자막 미리 받기")
    parser.add_argument("--count", type=int, default=3, help="채널당 영상 수 (기본 3)")
    parser.add_argument("--status", action="store_true", help="캐시 현황만 확인")
    args = parser.parse_args()

    if args.status:
        return show_status()

    settings = load_settings()
    if not settings.channels:
        print("[!] AGENT_CHANNELS 가 비어 있습니다.")
        return 1

    print("영상 목록을 가져오는 중...")
    videos, errors = fetch_channels(list(settings.channels))
    for cid, err in errors:
        print(f"  [!] {cid}: {err[:70]}")
    if not videos:
        print("[!] 가져온 영상이 없습니다.")
        return 1

    # 채널당 최신 N개
    picked: list = []
    per_channel: dict[str, int] = {}
    for v in videos:
        n = per_channel.get(v.channel, 0)
        if n < args.count:
            picked.append(v)
            per_channel[v.channel] = n + 1

    print(f"영상 {len(videos)}개 중 {len(picked)}개를 받습니다 "
          f"(채널 {len(per_channel)}개 × 최대 {args.count}개)\n")

    ok = cached = failed = blocked = 0
    for i, v in enumerate(picked, 1):
        if load_cached(v.video_id) is not None:
            cached += 1
            print(f"  [{i:>2}/{len(picked)}] 캐시됨  {v.title[:42]}")
            continue

        result = fetch_transcript(v.video_id)
        if result.available:
            ok += 1
            mark = f"{len(result.snippets)}줄 ({result.language})"
            print(f"  [{i:>2}/{len(picked)}] 받음    {v.title[:42]}  {mark}")
        elif result.error and "Blocked" in result.error:
            blocked += 1
            print(f"  [{i:>2}/{len(picked)}] 차단    {v.title[:42]}")
            if blocked >= 3:
                print("\n[중단] 유튜브가 요청을 차단하고 있습니다.")
                print("       10~30분 뒤에 다시 실행해 주세요. 이미 받은 것은 캐시에 남아 있습니다.")
                break
        else:
            failed += 1
            print(f"  [{i:>2}/{len(picked)}] 자막없음 {v.title[:42]}")

        if i < len(picked):
            time.sleep(PAUSE_SECONDS)

    print(f"\n새로 받음 {ok} · 이미 있음 {cached} · 자막 없음 {failed} · 차단 {blocked}")
    show_status()
    if blocked:
        print("\n차단된 영상은 나중에 다시 실행하면 이어서 받습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
