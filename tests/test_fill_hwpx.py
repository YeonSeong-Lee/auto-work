#!/usr/bin/env python3
"""fill_hwpx / verify_hwpx 회귀 테스트.

  python3 tests/test_fill_hwpx.py

외부 의존이 없어 디스코드 연결 없이도 언제든 돌릴 수 있다.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "sample_draft.json"
TEMPLATE = ROOT / "templates" / "daily.hwpx"


def run_case(name: str, draft: dict, workdir: Path, should_fail: bool) -> bool:
    draft_path = workdir / f"{name}.json"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    out = workdir / f"{name}.hwpx"

    fill = subprocess.run(
        [sys.executable, str(ROOT / "tools/fill_hwpx.py"), "--in", str(draft_path),
         "--template", str(TEMPLATE), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT,
    )
    if fill.returncode != 0:
        detail = (fill.stderr.strip().splitlines() or ["(무출력)"])[-1]
        ok = should_fail
    else:
        verify = subprocess.run(
            [sys.executable, str(ROOT / "tools/verify_hwpx.py"), str(out), "--against", str(draft_path)],
            capture_output=True, text=True, cwd=ROOT,
        )
        detail = (verify.stdout.strip().splitlines() or ["(무출력)"])[-1].strip()
        ok = (verify.returncode != 0) == should_fail

    print(f"{'PASS' if ok else 'FAIL'}  {name:22} → {detail}")
    return ok


def main() -> None:
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    results = []

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        results.append(run_case("정상_초안", base, work, should_fail=False))

        # 내역이 없는 칸은 '해당 없음'으로 채워져야 한다 (AC-6)
        empty = copy.deepcopy(base)
        empty["counseling_lines"] = []
        empty["guidance_lines"] = []
        empty["counts"] = {"first_response": 3, "learning_support": 0, "guidance": 0}
        results.append(run_case("빈_내역", empty, work, should_fail=False))

        # 요약은 한 문장이어야 한다 (AC-5)
        multi = copy.deepcopy(base)
        multi["summary"] = "분위기는 좋았습니다. 문의가 많았습니다."
        results.append(run_case("요약_여러문장", multi, work, should_fail=True))

        # 필수값이 없으면 생성 자체를 거부한다
        missing = copy.deepcopy(base)
        missing.pop("author")
        results.append(run_case("필수값_누락", missing, work, should_fail=True))

        # counts가 없어도 '총 0건'으로 채워진다
        no_counts = copy.deepcopy(base)
        no_counts["counts"] = {}
        results.append(run_case("건수_기본값", no_counts, work, should_fail=False))

        # XML 특수문자가 깨지지 않아야 한다
        special = copy.deepcopy(base)
        special["handover_lines"] = ['<태그> & "따옴표" 처리가 필요합니다.']
        results.append(run_case("XML_이스케이프", special, work, should_fail=False))

        # 항목 수가 늘어나도 문단이 복제되어야 한다 (수용량 7줄 이내)
        many = copy.deepcopy(base)
        many["inquiry_lines"] = [f"[문의 {i}] 항목 {i} 문의입니다." for i in range(1, 8)]
        results.append(run_case("다문단_7줄", many, work, should_fail=False))

        # 셀 높이를 넘으면 표가 밀리므로 잡아야 한다
        overflowing = copy.deepcopy(base)
        overflowing["inquiry_lines"] = [f"[문의 {i}] 항목 {i} 문의입니다." for i in range(1, 21)]
        results.append(run_case("셀높이_초과", overflowing, work, should_fail=True))

        # 요약이 한 줄을 넘으면 잡아야 한다 (셀 높이가 정확히 한 줄이다)
        long_summary = copy.deepcopy(base)
        long_summary["summary"] = (
            "전반적으로 학습 분위기는 안정적이었으나 파이썬 가상환경 설정 문의가 "
            "반복되어 별도 안내가 필요한 상황입니다."
        )
        results.append(run_case("요약_한줄초과", long_summary, work, should_fail=True))

        # 원본 템플릿은 안내문구가 남아 있으므로 반드시 실패해야 한다 (검사기 역검증)
        untouched = subprocess.run(
            [sys.executable, str(ROOT / "tools/verify_hwpx.py"), str(TEMPLATE)],
            capture_output=True, text=True, cwd=ROOT,
        )
        ok = untouched.returncode != 0
        results.append(ok)
        print(f"{'PASS' if ok else 'FAIL'}  {'원본_템플릿_역검증':22} → "
              f"{'예상대로 실패' if ok else '실패해야 하는데 통과함'}")

    print(f"\n전체: {'PASS' if all(results) else 'FAIL'} ({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
