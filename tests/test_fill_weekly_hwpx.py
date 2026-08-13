#!/usr/bin/env python3
"""fill_weekly_hwpx / verify_weekly_hwpx 회귀 테스트.

  python3 tests/test_fill_weekly_hwpx.py

붙임2 양식(templates/weekly.signed.hwpx)은 서명과 교육생 실명이 들어 있어 저장소에
없다. 양식이 없으면 전체를 SKIP한다 — 클론 직후에도 테스트가 빨갛게 뜨지 않아야 한다.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "sample_weekly_draft.json"

sys.path.insert(0, str(ROOT / "tools"))
from fill_weekly_hwpx import default_out, default_template  # noqa: E402

TEMPLATE = ROOT / default_template()


def run_case(name: str, draft: dict, workdir: Path, should_fail: bool, *, extra: list[str] | None = None) -> bool:
    draft_path = workdir / f"{name}.json"
    draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    out = workdir / f"{name}.hwpx"

    fill = subprocess.run(
        [sys.executable, str(ROOT / "tools/fill_weekly_hwpx.py"), "--in", str(draft_path),
         "--template", str(TEMPLATE), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT,
    )
    if fill.returncode != 0:
        detail = (fill.stderr.strip().splitlines() or ["(무출력)"])[-1]
        ok = should_fail
    else:
        verify = subprocess.run(
            [sys.executable, str(ROOT / "tools/verify_weekly_hwpx.py"), str(out),
             "--against", str(draft_path), "--template", str(TEMPLATE), *(extra or [])],
            capture_output=True, text=True, cwd=ROOT,
        )
        detail = (verify.stdout.strip().splitlines() or ["(무출력)"])[-1].strip()
        ok = (verify.returncode != 0) == should_fail

    print(f"{'PASS' if ok else 'FAIL'}  {name:22} → {detail}")
    return ok


def run_naming_case() -> bool:
    """제출용 파일명은 운영팀 요구 형식이라 어긋나면 반려된다."""
    draft = json.loads(FIXTURE.read_text(encoding="utf-8"))  # 2026-07-27 (월), 홍길동
    expected = "[코디세이]0727~0802_홍길동_퍼실리테이터_주간일지.hwpx"
    got = default_out(draft).name
    ok = got == expected
    print(f"{'PASS' if ok else 'FAIL'}  {'제출용_파일명':22} → {got}")
    return ok


def run_week_normalisation_case() -> bool:
    """주 중간 날짜를 줘도 그 주 월요일~일요일로 잡아야 한다."""
    from fill_weekly_hwpx import format_week

    midweek = {"week_start": "2026-07-30", "author": "홍길동"}  # 목요일
    ok = format_week(midweek) == "2026. 07. 27. ~ 2026. 08. 02."
    print(f"{'PASS' if ok else 'FAIL'}  {'주간_정규화':22} → {format_week(midweek)}")
    return ok


def run_signature_case(workdir: Path) -> bool:
    """작성자 칸의 서명 도장이 살아남아야 한다."""
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "tools"))
    from fill_weekly_hwpx import CELL
    from hwpx import HP, find_weekly_table, load_section, table_cells

    original = table_cells(find_weekly_table(load_section(TEMPLATE)))[CELL["author"]]
    if next(original.iter(HP + "pic"), None) is None:
        print(f"SKIP  {'서명_유지':22} → 양식에 서명이 없습니다")
        return True

    out = workdir / "sign.hwpx"
    draft = json.loads(FIXTURE.read_text(encoding="utf-8"))
    path = workdir / "sign.json"
    path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    subprocess.run(
        [sys.executable, str(ROOT / "tools/fill_weekly_hwpx.py"), "--in", str(path),
         "--template", str(TEMPLATE), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )
    made = table_cells(find_weekly_table(load_section(out)))[CELL["author"]]
    ok = next(made.iter(HP + "pic"), None) is not None
    print(f"{'PASS' if ok else 'FAIL'}  {'서명_유지':22} → {'서명 그대로 유지됨' if ok else '서명이 사라짐'}")
    return ok


def run_memo_case(workdir: Path) -> bool:
    """출석률 칸의 운영팀 메모는 값을 바꿔도 남아 있어야 한다."""
    from fill_weekly_hwpx import CELL
    from hwpx import cell_text, find_weekly_table, load_section, table_cells

    out = workdir / "memo.hwpx"
    draft = json.loads(FIXTURE.read_text(encoding="utf-8"))
    path = workdir / "memo.json"
    path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
    subprocess.run(
        [sys.executable, str(ROOT / "tools/fill_weekly_hwpx.py"), "--in", str(path),
         "--template", str(TEMPLATE), "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT, check=True,
    )
    tc = table_cells(find_weekly_table(load_section(out)))[CELL["attendance"]]
    ok = "출결률 평균값" in cell_text(tc) and "출결률 평균값" not in cell_text(tc, deep=False)
    print(f"{'PASS' if ok else 'FAIL'}  {'메모_보존':22} → "
          f"{'메모 유지, 본문과 분리됨' if ok else '메모가 사라졌거나 본문에 섞임'}")
    return ok


def main() -> None:
    if not TEMPLATE.exists():
        print(f"SKIP — 주간 양식이 없습니다 ({TEMPLATE.relative_to(ROOT)})")
        print("운영팀 붙임2 파일을 그 경로에 두면 검사합니다.")
        sys.exit(0)

    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    results = []

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        results.append(run_case("정상_초안", base, work, should_fail=False))

        # 서술 칸이 비면 '해당 없음'이 들어가고 그대로 통과해야 한다
        empty = copy.deepcopy(base)
        for key in ("improvement_lines", "student_issue_lines", "handover_lines", "next_week_lines"):
            empty[key] = []
        results.append(run_case("빈_서술칸", empty, work, should_fail=False))

        # 필수값이 없으면 만들지 않고 멈춰야 한다
        missing = copy.deepcopy(base)
        del missing["author"]
        results.append(run_case("필수값_누락", missing, work, should_fail=True))

        # 진도율 칸 수가 어긋나면 조용히 밀어 넣지 말고 멈춰야 한다
        short = copy.deepcopy(base)
        short["progress"] = [1, 2, 3]
        results.append(run_case("진도율_칸수_불일치", short, work, should_fail=True))

        # 운영팀 데이터를 주지 않으면 지난 주 값(교육생 실명 포함)이 그대로 남는다 -> 반드시 실패
        no_operator = copy.deepcopy(base)
        for key in ("attendance_rate", "attendance_average", "progress", "risk_students"):
            no_operator.pop(key, None)
        results.append(run_case("운영팀_데이터_누락", no_operator, work, should_fail=True))

        # 확인했다면 --allow-stale로 넘어갈 수 있어야 한다
        results.append(
            run_case("잔존_허용", no_operator, work, should_fail=False, extra=["--allow-stale"])
        )

        # 서술 칸이 넘치면 표가 밀리므로 잡아야 한다
        overflowing = copy.deepcopy(base)
        overflowing["next_week_lines"] = [f"- 계획 항목 {i}번입니다." for i in range(1, 21)]
        results.append(run_case("셀높이_초과", overflowing, work, should_fail=True))

        # XML 특수문자가 깨지지 않아야 한다
        escaped = copy.deepcopy(base)
        escaped["handover_lines"] = ["- <태그> & \"따옴표\" 처리 확인"]
        results.append(run_case("XML_이스케이프", escaped, work, should_fail=False))

        results.append(run_signature_case(work))
        results.append(run_memo_case(work))
        results.append(run_week_normalisation_case())
        results.append(run_naming_case())

    print(f"\n전체: {'PASS' if all(results) else 'FAIL'} ({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
