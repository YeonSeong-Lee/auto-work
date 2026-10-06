#!/usr/bin/env python3
"""완성된 일지 HWPX를 구글 드라이브 제출 폴더에 올린다.

  python3 tools/upload_drive.py "out/[코디세이]0731(금)_이성연_퍼실리테이터 일일업무일지.hwpx"
  python3 tools/upload_drive.py <파일> --dry-run          # 어디로 올라가는지만 확인
  python3 tools/upload_drive.py <파일> --folder <URL|ID>  # 이번만 다른 폴더로

업로드 대상은 코드가 아니라 config.toml의 [drive]에서 읽는다. 폴더가 바뀌면 그 한 줄만 고친다.

전송은 rclone에 맡긴다. OAuth 토큰 갱신을 직접 다루지 않기 위해서다.
`rclone copyto`는 같은 이름이 있으면 그 파일을 갱신하므로(파일 ID가 유지된다) 초안을 고쳐
다시 올려도 폴더에 하루치 파일이 하나만 남고 공유 링크도 그대로다.

드라이브에 올리는 이름은 항상 완성형(NFC)으로 바꾼다. macOS에서 넘어온 자모 분리형(NFD)
이름은 맥에선 멀쩡해 보여도 Windows에서 ㅋㅗㄷㅣㅅㅔㅇㅣ처럼 깨져 보이기 때문이다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
import unicodedata
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REMOTE = "gdrive"
FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")


def folder_id_from(value: str) -> str:
    """폴더 설정값에서 ID를 뽑는다. 주소창을 그대로 붙여넣어도 되게 하기 위함이다."""
    text = str(value).strip()

    if text.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(text)
        segments = [s for s in parsed.path.split("/") if s]
        if "folders" in segments and segments.index("folders") + 1 < len(segments):
            candidate = segments[segments.index("folders") + 1]
        else:  # .../open?id=<ID> 형태
            candidate = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
    else:
        candidate = text

    if not FOLDER_ID.match(candidate):
        raise SystemExit(
            f"드라이브 폴더를 알아볼 수 없습니다: {value!r}\n"
            "폴더를 연 뒤 주소창을 그대로 붙여넣으세요 "
            "(https://drive.google.com/drive/folders/... 형태) — 폴더 ID만 넣어도 됩니다."
        )
    return candidate


def load_drive_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8")).get("drive", {})


def resolve_folder(override: str | None, config: dict) -> str | None:
    """--folder > [drive].folder_id > [drive].folder. 아무것도 없으면 None(업로드 안 함)."""
    for value in (override, config.get("folder_id"), config.get("folder")):
        if value:
            return folder_id_from(value)
    return None


def rclone(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["rclone", *args], capture_output=True, text=True)


def require_remote(remote: str) -> None:
    if not shutil.which("rclone"):
        raise SystemExit(
            "rclone이 설치되어 있지 않습니다.\n"
            "  brew install rclone && rclone config\n"
            "업로드 없이 로컬 파일만 만들려면 /daily-log --no-upload 를 쓰세요."
        )

    listed = rclone(["listremotes"])
    if listed.returncode != 0:
        raise SystemExit(f"rclone 리모트 목록을 읽지 못했습니다.\n{listed.stderr.strip()}")

    if f"{remote}:" not in listed.stdout.split():
        available = " ".join(listed.stdout.split()) or "(없음)"
        raise SystemExit(
            f"rclone 리모트 '{remote}'가 없습니다. 현재 설정된 리모트: {available}\n"
            f"  rclone config   # n → 이름 {remote} → drive → 브라우저 인증\n"
            "이름을 다르게 만들었다면 config.toml의 [drive].remote를 맞춰 주세요."
        )


def web_link(remote: str, folder: str, name: str) -> str:
    """올라간 파일의 링크. 조회에 실패하면 폴더 링크로 대신한다 — 전송은 이미 끝났다."""
    listed = rclone(["lsjson", "--files-only", f"{remote},root_folder_id={folder}:"])
    if listed.returncode == 0:
        try:
            for entry in json.loads(listed.stdout):
                if unicodedata.normalize("NFC", entry.get("Name", "")) == name and entry.get("ID"):
                    return f"https://drive.google.com/file/d/{entry['ID']}/view"
        except json.JSONDecodeError:
            pass
    return f"https://drive.google.com/drive/folders/{folder}"


def main() -> None:
    ap = argparse.ArgumentParser(description="일지 HWPX를 구글 드라이브에 업로드")
    ap.add_argument("path", help="업로드할 파일 (fill_hwpx.py가 출력한 경로)")
    ap.add_argument("--folder", help="대상 폴더 URL 또는 ID. config.toml의 [drive]를 덮어쓴다")
    ap.add_argument("--config", default=str(ROOT / "config.toml"))
    ap.add_argument("--dry-run", action="store_true", help="대상만 확인하고 올리지 않는다")
    args = ap.parse_args()

    source = Path(args.path)
    if not source.is_file():
        raise SystemExit(f"업로드할 파일이 없습니다: {source}")

    config = load_drive_config(Path(args.config))
    folder = resolve_folder(args.folder, config)
    if not folder:
        # 설정하지 않은 것은 실패가 아니다. 드라이브 없이 out/까지만 쓰는 사용법을 남겨 둔다.
        print("업로드 건너뜀 ([drive] 미설정) — config.toml에 [drive]를 추가하면 자동으로 올라갑니다.")
        return

    remote = config.get("remote", DEFAULT_REMOTE)
    require_remote(remote)
    name = unicodedata.normalize("NFC", source.name)
    target = f"{remote},root_folder_id={folder}:{name}"

    if args.dry_run:
        print(f"업로드 대상: {remote}: 폴더 {folder}")
        print(f"파일명: {name}")
        return

    result = rclone(["copyto", str(source), target])
    if result.returncode != 0:
        raise SystemExit(
            f"드라이브 업로드에 실패했습니다 (rclone {result.returncode}).\n"
            f"{result.stderr.strip()}\n"
            f"파일은 {source} 에 그대로 있습니다. 폴더 ID와 접근 권한을 확인하세요."
        )

    print(web_link(remote, folder, name))


if __name__ == "__main__":
    main()
