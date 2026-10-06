#!/usr/bin/env python3
"""form_link 회귀 테스트.

  python3 tests/test_form_link.py

--schema로 저장해 둔 더미 폼 정의를 넘겨 실제 폼을 조회하지 않는다. 브라우저를 띄우는지는
PATH 앞에 가짜 open을 심어 확인한다. 네트워크도 구글 계정도 쓰지 않는다.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORM_LINK = ROOT / "tools" / "form_link.py"
SCHEMA = ROOT / "fixtures" / "sample_form_schema.json"
SAMPLE = ROOT / "fixtures" / "sample_draft.json"

FORM_URL = "https://docs.google.com/forms/d/e/SAMPLE_FORM_ID/viewform"
CONFIG = f'[form]\nurl = "{FORM_URL}"\nexclusive = ["특이사항 없음"]\n'

ACTIVITY = "entry.111111111"
NOTE = "entry.222222222"
TEXT = "entry.333333333"

# 인자를 한 줄에 하나씩 남긴다. URL에 공백과 괄호가 섞여 한 줄로 합치면 경계가 뭉개진다.
FAKE_OPEN = """#!/bin/sh
for arg in "$@"; do printf '%s\\n' "$arg" >>"$OPEN_LOG"; done
exit "$OPEN_RC"
"""

counter = 0


def run(work: Path, form, *extra: str, config: str = CONFIG, open_rc: int = 0,
        schema: Path | None = SCHEMA, draft: dict | None = None) -> tuple:
    """링크 생성기를 한 번 돌리고 (종료코드, stdout, stderr, open에 넘어간 인자들)을 준다."""
    global counter
    counter += 1
    case = work / f"case{counter}"
    bindir = case / "bin"
    bindir.mkdir(parents=True)

    log = case / "open.log"
    for name in ("open", "xdg-open"):  # 플랫폼에 따라 둘 중 하나를 부른다
        shim = bindir / name
        shim.write_text(FAKE_OPEN, encoding="utf-8")
        shim.chmod(0o755)

    config_path = case / "config.toml"
    config_path.write_text(config, encoding="utf-8")

    base = draft if draft is not None else json.loads(SAMPLE.read_text(encoding="utf-8"))
    if form is None:
        base.pop("form", None)
    else:
        base["form"] = form
    draft_path = case / "draft.json"
    draft_path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")

    args = ["--in", str(draft_path), "--config", str(config_path)]
    if schema is not None:
        args += ["--schema", str(schema)]

    env = {**os.environ, "PATH": str(bindir), "OPEN_LOG": str(log), "OPEN_RC": str(open_rc)}
    done = subprocess.run(
        [sys.executable, str(FORM_LINK), *args, *extra],
        capture_output=True, text=True, cwd=ROOT, env=env,
    )
    opened = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return done.returncode, done.stdout, done.stderr, opened


def params_of(stdout: str) -> dict:
    """stdout 마지막 줄을 링크로 보고 파라미터를 뜯는다."""
    link = stdout.strip().splitlines()[-1]
    return urllib.parse.parse_qs(urllib.parse.urlparse(link).query, keep_blank_values=True)


def check(name: str, ok: bool, detail: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name:24} → {detail}")
    return ok


def first_line(text: str) -> str:
    return (text.strip().splitlines() or ["(무출력)"])[0]


def main() -> None:
    results = []
    good = json.loads(SAMPLE.read_text(encoding="utf-8"))["form"]

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        # 정상 경로 — 고른 보기가 그대로 실려 나가야 한다
        code, out, err, opened = run(work, good)
        query = params_of(out) if code == 0 else {}
        ok = (code == 0
              and query.get(ACTIVITY) == good["activities"]
              and query.get(NOTE) == good["notes"]
              and query.get(TEXT) == [good["field_note"]]
              and query.get("usp") == ["pp_url"])
        results.append(check("정상_파라미터", ok, first_line(out) if ok else first_line(err)))

        # stdout은 링크 전용이어야 한다. scripts/log.sh가 앞줄을 grep으로 집는다
        results.append(check("stdout_링크단독",
                             code == 0 and len(out.strip().splitlines()) == 1
                             and out.strip().startswith(FORM_URL),
                             out.strip() or "(무출력)"))

        # 요약은 stderr로 — 마지막 줄 계약을 건드리면 안 된다
        results.append(check("요약_stderr", "주요 활동" in err, first_line(err)))

        # 기타는 표식 + 짝 파라미터 두 개로 나간다. 텍스트만 보내면 구글이 버린다
        other = {**good, "activities": [], "activities_other": "야간 자율학습 감독"}
        code, out, err, _ = run(work, other)
        query = params_of(out) if code == 0 else {}
        ok = (code == 0
              and query.get(ACTIVITY) == ["__other_option__"]
              and query.get(f"{ACTIVITY}.other_option_response") == ["야간 자율학습 감독"])
        results.append(check("기타_인코딩", ok, first_line(out) if ok else first_line(err)))

        # 여기가 이 스크립트의 존재 이유다 — 구글은 틀린 보기를 오류 없이 버린다
        code, _, err, _ = run(work, {**good, "activities": ["없는 보기입니다"]})
        results.append(check("없는_보기", code != 0 and "폼에 없는 보기" in err, first_line(err)))

        # 유효한 보기 목록을 같이 보여줘야 고칠 수 있다
        results.append(check("없는_보기_안내", "질의응답 및 학습 진행 지원" in err,
                             "유효 보기 목록 출력됨" if "질의응답" in err else err.strip()))

        code, _, err, _ = run(work, {**good, "activities": [], "activities_other": ""})
        results.append(check("필수_공백", code != 0 and "비어 있습니다" in err, first_line(err)))

        code, _, err, _ = run(work, {**good, "field_note": "   "})
        results.append(check("서술형_공백", code != 0 and "비어 있습니다" in err, first_line(err)))

        # '특이사항 없음'과 다른 보기를 같이 고르면 모순이다
        code, _, err, _ = run(work, {**good, "notes": ["특이사항 없음", "추가 지원 필요 사항"]})
        results.append(check("단독보기_위반", code != 0 and "단독으로만" in err, first_line(err)))

        # 단독이면 통과해야 한다 (검사가 과하게 걸리면 못 쓴다)
        code, out, err, _ = run(work, {**good, "notes": ["특이사항 없음"]})
        results.append(check("단독보기_정상", code == 0, first_line(out) if code == 0 else first_line(err)))

        # exclusive를 설정하지 않았으면 이 검사는 걸리지 않는다
        code, _, _, _ = run(work, {**good, "notes": ["특이사항 없음", "추가 지원 필요 사항"]},
                            config=f'[form]\nurl = "{FORM_URL}"\n')
        results.append(check("단독보기_미설정", code == 0, f"exit {code}"))

        # form 블록이 없는 건 조용히 넘어갈 일이 아니다 — 폼이 안 채워진 채 끝난다
        code, _, err, _ = run(work, None)
        results.append(check("form_블록_없음", code != 0 and "form 블록이 없습니다" in err,
                             first_line(err)))

        # 설정하지 않은 것은 실패가 아니다 — 폼 없이 HWPX까지만 쓰는 사용법이 살아 있어야 한다
        code, out, _, _ = run(work, good, config='author = "홍길동"\n')
        results.append(check("미설정_건너뜀", code == 0 and "건너뜀" in out, first_line(out)))

        # 설정이 없으면 초안에 form이 없어도 실패하지 않는다 (건너뛰기가 먼저다)
        code, out, _, _ = run(work, None, config='author = "홍길동"\n')
        results.append(check("미설정_form없어도", code == 0 and "건너뜀" in out, first_line(out)))

        # --open 없이 브라우저를 띄우면 안 된다
        code, out, _, opened = run(work, good)
        results.append(check("open_기본_안띄움", code == 0 and not opened,
                             f"open 호출: {opened or '없음'}"))

        code, out, _, opened = run(work, good, "--open")
        ok = code == 0 and len(opened) == 1 and opened[0].startswith(FORM_URL)
        results.append(check("open_플래그", ok, first_line(opened[0]) if opened else "호출 없음"))

        # 브라우저를 못 띄워도 링크는 나와야 한다. 복사해서 열면 되는 일이다
        code, out, err, _ = run(work, good, "--open", open_rc=1)
        results.append(check("open_실패해도_링크",
                             code == 0 and out.strip().startswith(FORM_URL)
                             and "띄우지 못했습니다" in err,
                             first_line(err)))

        # 폼이 바뀌어 문항 수가 달라지면 조용히 어긋나지 말고 멈춰야 한다
        changed = json.loads(SCHEMA.read_text(encoding="utf-8"))
        changed["questions"].append(copy.deepcopy(changed["questions"][0]))
        changed_path = work / "changed_schema.json"
        changed_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        code, _, err, _ = run(work, good, schema=changed_path)
        results.append(check("폼구성_바뀜", code != 0 and "폼 구성이 예상과 다릅니다" in err,
                             first_line(err)))

        # --schema 를 주면 네트워크를 타지 않는다. 없는 파일은 조용히 폼 조회로 새지 말아야 한다
        code, _, err, _ = run(work, good, schema=work / "없는스키마.json")
        results.append(check("스키마_없는파일", code != 0 and "스키마 파일이 없습니다" in err,
                             first_line(err)))

        # 초안 자체가 없으면 만들었다고 하면 안 된다
        missing = subprocess.run(
            [sys.executable, str(FORM_LINK), "--in", str(work / "없는초안.json")],
            capture_output=True, text=True, cwd=ROOT,
        )
        results.append(check("초안_없음",
                             missing.returncode != 0 and "초안이 없습니다" in missing.stderr,
                             first_line(missing.stderr)))

    print(f"\n전체: {'PASS' if all(results) else 'FAIL'} ({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
