#!/usr/bin/env python3
"""지정한 날짜의 디스코드 채널 메시지를 수집해 JSON으로 내보낸다.

  python tools/fetch_discord.py --date 2026-07-30 --dry-run
  python tools/fetch_discord.py --date 2026-07-30 --out logs/2026-07-30.json

정식 봇 토큰만 사용한다. 사용자 계정 토큰(셀프봇)은 Discord ToS 위반이라 지원하지 않는다.
메시지 본문을 읽으려면 Developer Portal에서 MESSAGE CONTENT INTENT가 켜져 있어야 한다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://discord.com/api/v10"
DISCORD_EPOCH_MS = 1420070400000
PAGE = 100
ROOT = Path(__file__).resolve().parent.parent


def snowflake(moment: dt.datetime) -> int:
    """시각을 디스코드 스노우플레이크 ID로 바꾼다. 페이지네이션 경계로 쓴다."""
    return (int(moment.timestamp() * 1000) - DISCORD_EPOCH_MS) << 22


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"설정 파일이 없습니다: {path}\nconfig.example.toml을 복사해 만드세요.")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "DISCORD_BOT_TOKEN":
                    token = value.strip().strip("\"'")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN이 없습니다. .env에 넣거나 환경변수로 주세요.")
    return token


def request(path: str, token: str, params: dict | None = None) -> list | dict:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bot {token}"})

    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 429:  # 레이트리밋 — Retry-After만큼 기다렸다 재시도
                wait = float(error.headers.get("Retry-After", 1)) + 0.5
                time.sleep(min(wait, 30))
                continue
            body = error.read().decode("utf-8", "replace")[:200]
            if error.code == 403:
                raise SystemExit(f"권한 없음 ({path}). 봇이 채널을 읽을 수 있는지 확인하세요.\n{body}")
            if error.code == 401:
                raise SystemExit("토큰이 거부되었습니다. DISCORD_BOT_TOKEN을 확인하세요.")
            raise SystemExit(f"디스코드 API 오류 {error.code} ({path}): {body}")
    raise SystemExit(f"레이트리밋이 계속되어 포기했습니다: {path}")


def fetch_channel(channel_id: str, token: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
    """[start, end) 구간의 메시지를 수집한다. 최신 → 과거 방향으로 거슬러 올라간다."""
    collected = []
    cursor = snowflake(end)

    while True:
        batch = request(f"/channels/{channel_id}/messages", token, {"limit": PAGE, "before": cursor})
        if not batch:
            break

        reached_start = False
        for message in batch:
            when = dt.datetime.fromisoformat(message["timestamp"])
            if when < start:
                reached_start = True
                continue
            if when >= end:
                continue
            collected.append(message)

        if reached_start or len(batch) < PAGE:
            break
        cursor = batch[-1]["id"]

    return collected


def active_threads(guild_id: str, token: str, parents: set[str]) -> list[dict]:
    """대상 채널에 딸린 활성 스레드 목록. 문의가 스레드에서 오가는 경우를 놓치지 않기 위함."""
    result = request(f"/guilds/{guild_id}/threads/active", token)
    return [t for t in result.get("threads", []) if t.get("parent_id") in parents]


def normalize(message: dict, channel_name: str) -> dict:
    author = message.get("author") or {}
    referenced = message.get("referenced_message") or {}
    return {
        "channel": channel_name,
        "author": author.get("global_name") or author.get("username", "알 수 없음"),
        "is_bot": bool(author.get("bot")),
        "content": message.get("content", ""),
        "timestamp": message["timestamp"],
        "reply_to": (referenced.get("author") or {}).get("username"),
        "attachments": len(message.get("attachments") or []),
    }


def collect(config: dict, token: str, date: dt.date) -> list[dict]:
    tz = dt.timezone(dt.timedelta(hours=config.get("timezone_offset", 9)))
    work = config.get("work_hours", {})
    start = dt.datetime.combine(date, dt.time.fromisoformat(work.get("start", "09:00")), tz)
    end = dt.datetime.combine(date, dt.time.fromisoformat(work.get("end", "18:00")), tz)

    targets = {str(c["id"]): c.get("name", str(c["id"])) for c in config.get("channels", [])}
    if not targets:
        raise SystemExit("config.toml에 [[channels]]가 하나도 없습니다.")

    guild_id = config.get("guild_id")
    if guild_id:
        for thread in active_threads(str(guild_id), token, set(targets)):
            parent = targets.get(thread.get("parent_id"), "")
            targets[thread["id"]] = f"{parent}/{thread.get('name', '스레드')}"

    messages = []
    for channel_id, name in targets.items():
        for message in fetch_channel(channel_id, token, start, end):
            entry = normalize(message, name)
            if entry["is_bot"] or not (entry["content"] or entry["attachments"]):
                continue
            messages.append(entry)

    messages.sort(key=lambda m: m["timestamp"])
    return messages


def main() -> None:
    ap = argparse.ArgumentParser(description="디스코드 하루치 로그 수집")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="대상 날짜 (YYYY-MM-DD)")
    ap.add_argument("--config", default=str(ROOT / "config.toml"))
    ap.add_argument("--out", help="출력 JSON 경로 (미지정 시 표준출력)")
    ap.add_argument("--dry-run", action="store_true", help="채널별 수집 건수만 출력 (권한 진단용)")
    args = ap.parse_args()

    config = load_config(Path(args.config))
    messages = collect(config, load_token(), dt.date.fromisoformat(args.date))

    if args.dry_run:
        print(f"{args.date} 수집 결과: 총 {len(messages)}건")
        by_channel: dict[str, int] = {}
        for m in messages:
            by_channel[m["channel"]] = by_channel.get(m["channel"], 0) + 1
        for channel, count in sorted(by_channel.items()):
            print(f"  {channel}: {count}건")
        if not messages:
            print("\n0건입니다. MESSAGE CONTENT INTENT가 꺼져 있거나 채널 권한이 없을 수 있습니다.")
        return

    payload = json.dumps({"date": args.date, "messages": messages}, ensure_ascii=False, indent=2)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        print(path)
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
