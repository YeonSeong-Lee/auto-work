#!/usr/bin/env python3
"""upload_drive 회귀 테스트.

  python3 tests/test_upload_drive.py

PATH 앞에 가짜 rclone을 심어 호출 인자를 받아 본다. 네트워크도 드라이브 계정도 쓰지 않는다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPLOAD = ROOT / "tools" / "upload_drive.py"

FOLDER = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
OTHER = "9ZyXwVuTsRqPoNmLkJiHgFeDcBa543210"
FILENAME = "[코디세이]0731(금)_이성연_퍼실리테이터 일일업무일지.hwpx"

# 인자를 한 줄에 하나씩 남긴다. 파일명에 공백과 괄호가 있어 한 줄로 합치면 경계가 뭉개진다.
FAKE_RCLONE = """#!/bin/sh
for arg in "$@"; do printf '%s\\n' "$arg" >>"$RCLONE_LOG"; done
case "$1" in
  listremotes) printf '%s\\n' "$RCLONE_REMOTES" ;;
  lsjson) printf '%s\\n' "$RCLONE_LSJSON" ;;
  copyto) exit "$RCLONE_COPYTO_RC" ;;
esac
exit 0
"""

counter = 0


def run(work: Path, config: str, *extra: str, remotes: str = "gdrive:",
        lsjson: str = "[]", copyto_rc: int = 0, with_rclone: bool = True) -> tuple:
    """업로더를 한 번 돌리고 (종료코드, stdout, stderr, rclone에 넘어간 인자들)을 준다."""
    global counter
    counter += 1
    case = work / f"case{counter}"
    bindir = case / "bin"
    bindir.mkdir(parents=True)

    log = case / "rclone.log"
    if with_rclone:
        shim = bindir / "rclone"
        shim.write_text(FAKE_RCLONE, encoding="utf-8")
        shim.chmod(0o755)

    config_path = case / "config.toml"
    config_path.write_text(config, encoding="utf-8")

    source = case / FILENAME
    source.write_bytes(b"PK\x03\x04 not a real hwpx")

    env = {**os.environ, "PATH": str(bindir), "RCLONE_LOG": str(log),
           "RCLONE_REMOTES": remotes, "RCLONE_LSJSON": lsjson,
           "RCLONE_COPYTO_RC": str(copyto_rc)}

    done = subprocess.run(
        [sys.executable, str(UPLOAD), str(source), "--config", str(config_path), *extra],
        capture_output=True, text=True, cwd=ROOT, env=env,
    )
    args = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return done.returncode, done.stdout, done.stderr, args


def check(name: str, ok: bool, detail: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name:24} → {detail}")
    return ok


def main() -> None:
    results = []
    configured = f'[drive]\nremote = "gdrive"\nfolder = "{FOLDER}"\n'

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        # 설정하지 않은 것은 실패가 아니다 — 드라이브 없이 out/까지만 쓰는 사용법이 살아 있어야 한다
        code, out, _, args = run(work, 'author = "이성연"\n')
        results.append(check("미설정_건너뜀", code == 0 and "건너뜀" in out and not args,
                             out.strip() or "(무출력)"))

        # config.toml 자체가 없어도 같은 취급이다
        code, out, _, _ = run(work, "", "--config", str(work / "없는파일.toml"))
        results.append(check("설정파일_없음", code == 0 and "건너뜀" in out, out.strip() or "(무출력)"))

        code, _, err, _ = run(work, configured, with_rclone=False)
        results.append(check("rclone_미설치", code != 0 and "brew install rclone" in err,
                             (err.strip().splitlines() or ["(무출력)"])[0]))

        code, _, err, _ = run(work, configured, remotes="")
        results.append(check("리모트_미등록", code != 0 and "rclone config" in err,
                             (err.strip().splitlines() or ["(무출력)"])[0]))

        # 폴더는 주소창을 그대로 붙여넣어도, ID만 넣어도 같은 곳을 가리켜야 한다
        for label, value in [
            ("맨_ID", FOLDER),
            ("전체_URL", f"https://drive.google.com/drive/folders/{FOLDER}"),
            ("공유_URL", f"https://drive.google.com/drive/folders/{FOLDER}?usp=sharing"),
            ("open_id_URL", f"https://drive.google.com/open?id={FOLDER}"),
        ]:
            code, out, err, _ = run(work, f'[drive]\nfolder = "{value}"\n', "--dry-run")
            ok = code == 0 and FOLDER in out
            results.append(check(f"폴더설정_{label}", ok, (out or err).strip().splitlines()[0]))

        code, _, err, _ = run(work, '[drive]\nfolder = "내 제출 폴더"\n')
        results.append(check("폴더설정_잘못된값", code != 0 and "알아볼 수 없습니다" in err,
                             (err.strip().splitlines() or ["(무출력)"])[0]))

        # --folder는 설정을 덮어쓴다 (설정을 고치지 않고 한 번만 다른 곳에 올릴 때)
        code, out, _, _ = run(work, configured, "--dry-run", "--folder", OTHER)
        results.append(check("우선순위_인자", code == 0 and OTHER in out and FOLDER not in out,
                             out.strip().splitlines()[0]))

        # folder_id를 쓰던 설정이 있으면 그쪽이 이긴다 (하위 호환)
        both = f'[drive]\nfolder = "{FOLDER}"\nfolder_id = "{OTHER}"\n'
        code, out, _, _ = run(work, both, "--dry-run")
        results.append(check("우선순위_folder_id", code == 0 and OTHER in out,
                             out.strip().splitlines()[0]))

        # --dry-run은 확인만 한다. 실수로 올려 버리면 확인의 의미가 없다
        code, _, _, args = run(work, configured, "--dry-run")
        results.append(check("dry_run_전송안함", code == 0 and "copyto" not in args,
                             f"rclone 호출: {args or '없음'}"))

        # 정상 경로 — 설정에서 읽은 폴더와 제출용 파일명이 그대로 실려 나가야 한다
        listing = json.dumps([{"Name": FILENAME, "ID": "FILE123"}], ensure_ascii=False)
        code, out, err, args = run(work, configured, lsjson=listing)
        target = f"gdrive,root_folder_id={FOLDER}:{FILENAME}"
        ok = code == 0 and "copyto" in args and target in args
        results.append(check("업로드_인자", ok, target if ok else f"{err.strip()} / {args}"))

        results.append(check("링크_출력",
                             out.strip().splitlines()[-1:] == ["https://drive.google.com/file/d/FILE123/view"],
                             out.strip() or "(무출력)"))

        # 목록 조회가 실패해도 전송은 이미 끝났다. 폴더 링크로라도 안내해야 한다
        code, out, _, _ = run(work, configured, lsjson="깨진 JSON")
        results.append(check("링크_조회실패_대체",
                             code == 0 and out.strip().endswith(FOLDER), out.strip() or "(무출력)"))

        # 전송 실패를 성공으로 넘기면 제출이 안 된 채 끝난다
        code, _, err, _ = run(work, configured, copyto_rc=1)
        results.append(check("전송실패_보고", code != 0 and "업로드에 실패" in err,
                             (err.strip().splitlines() or ["(무출력)"])[0]))

        # 없는 파일을 올렸다고 하면 안 된다
        missing = subprocess.run(
            [sys.executable, str(UPLOAD), str(work / "없는파일.hwpx")],
            capture_output=True, text=True, cwd=ROOT,
        )
        results.append(check("대상파일_없음",
                             missing.returncode != 0 and "파일이 없습니다" in missing.stderr,
                             (missing.stderr.strip().splitlines() or ["(무출력)"])[0]))

    print(f"\n전체: {'PASS' if all(results) else 'FAIL'} ({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
