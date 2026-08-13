#!/usr/bin/env python3
"""산출 주간일지 hwpx가 제출 가능한 상태인지 검사한다.

  python tools/verify_weekly_hwpx.py "out/[코디세이]0810~0816_이성연_퍼실리테이터_주간일지.hwpx"
  python tools/verify_weekly_hwpx.py "<위 경로>" --against drafts/week-2026-08-10.json

일일 검사와 같은 항목(글자색·셀 높이·초안 대조)에 하나가 더 붙는다.

**잔존 검사가 이 양식에만 있는 이유.** 운영팀에서 받은 붙임2는 빈 양식이 아니라 지난 주
제출본이다. 출석률·진도율·이탈 위험 교육생 칸을 새 값으로 덮지 않으면 지난 주 숫자와
교육생 실명이 그대로 다시 제출된다. 눈으로는 채워져 있어 보이므로 기계로 잡는다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fill_weekly_hwpx import (
    CELL,
    EMPTY,
    NARRATIVE,
    PROGRESS_ROW,
    default_template,
    format_week,
    lines_or_empty,
)
from hwpx import (
    BLACK,
    HH,
    HP,
    cell_text,
    find_weekly_table,
    load_header,
    load_section,
    nested_table,
    own_paragraphs,
    table_cells,
    text_nodes,
)
from verify_hwpx import LINE_SPACING

# 양식에 원래 들어 있는 안내문구. 하나라도 남아 있으면 그 셀은 채워지지 않은 것이다.
PLACEHOLDERS = ["작성해 주세요", "2026. 00. 00.", "0000. 00. 00."]

# 초안이 값을 주지 않으면 fill이 손대지 않는 칸 -> 양식의 지난 주 값이 그대로 남는다.
# 칸 이름과 초안 키를 짝지어 둔다. 작성자·팀·서술 4칸은 항상 새로 쓰므로 여기 없다.
OPERATOR_FIELDS = {
    "attendance": ("attendance_rate", "attendance_average"),
    "progress": ("progress",),
    "risk": ("risk_students",),
}


def weekly_cells(path: str):
    return table_cells(find_weekly_table(load_section(path)))


def progress_values(cells) -> list[str]:
    inner = nested_table(cells[CELL["progress"]])
    if inner is None:
        return []
    row = table_cells(inner)
    width = max(col for r, col in row if r == PROGRESS_ROW) + 1
    return [cell_text(row[(PROGRESS_ROW, col)], deep=False) for col in range(width)]


def check_placeholders(cells) -> list[str]:
    problems = []
    for (row, col), tc in sorted(cells.items()):
        text = cell_text(tc, deep=False)
        for token in PLACEHOLDERS:
            if token in text:
                problems.append(f"r{row}c{col}: 안내문구 잔존 — {token!r}")
        if text.strip() in {"-", "- "}:
            problems.append(f"r{row}c{col}: 글머리만 있고 내용이 비었습니다")
    return problems


def check_stale(path: str, template: Path, draft: dict | None) -> list[str]:
    """지난 주 제출본의 값이 그대로 남아 있는 칸을 찾는다.

    초안이 값을 준 칸은 fill이 새로 썼으므로 보지 않는다. 이번 주 숫자가 지난 주와
    우연히 같을 수 있는데, 그건 잘못이 아니다. 위험한 쪽은 값을 아예 주지 않아 양식의
    지난 주 내용이 그대로 제출되는 경우다.
    """
    made = weekly_cells(path)
    origin = weekly_cells(str(template)) if template.exists() else None

    problems = []
    for name, keys in OPERATOR_FIELDS.items():
        if draft is not None and any(draft.get(key) for key in keys):
            continue

        if name == "progress":
            values = progress_values(made)
            left = ", ".join(values[:4]) if values else ""
            stale = bool(values) and (origin is None or values == progress_values(origin))
        else:
            got = cell_text(made[CELL[name]], deep=False).strip()
            left = got[:40]
            stale = bool(got) and (origin is None or got == cell_text(origin[CELL[name]], deep=False).strip())

        if stale:
            problems.append(
                f"{name}: 이번 주 값을 주지 않아 양식의 지난 주 내용이 그대로 남아 있습니다 "
                f"({left!r}) — 운영팀 시트에서 받아 채우세요"
            )
    return problems


def check_colors(path: str, cells) -> list[str]:
    """채운 셀의 글자가 검은색인지 본다. 양식의 안내문구 색을 물려받는 사고를 막는다."""
    colors = {
        cp.get("id"): (cp.get("textColor") or "").upper()
        for cp in load_header(path).iter(HH + "charPr")
    }

    problems = []
    for name, (row, col) in CELL.items():
        seen = set()
        for run in cells[(row, col)].iter(HP + "run"):
            color = colors.get(run.get("charPrIDRef"))
            if color and color != BLACK:
                seen.add(color)
        for color in sorted(seen):
            problems.append(f"r{row}c{col} ({name}): 글자색이 검정이 아닙니다 — {color}")
    return problems


def check_overflow(path: str, cells) -> list[str]:
    """셀 높이를 넘는 내용이 있는지 본다. 계산 방식은 일일 검사와 같다.

    메모와 중첩표의 글은 세지 않는다. 셀 본문이 아니라서 높이를 먹지 않는다.
    """
    fonts = {
        cp.get("id"): int(cp.get("height") or 0)
        for cp in load_header(path).iter(HH + "charPr")
    }

    problems = []
    for name, (row, col) in CELL.items():
        if name == "progress":  # 안쪽이 표라 줄 수로 잴 수 없다
            continue
        tc = cells[(row, col)]
        size, margin = tc.find(HP + "cellSz"), tc.find(HP + "cellMargin")
        inner_width = int(size.get("width")) - int(margin.get("left")) - int(margin.get("right"))
        inner_height = int(size.get("height")) - int(margin.get("top")) - int(margin.get("bottom"))

        needed, cell_font = 0, 0
        for p in own_paragraphs(tc):
            run = p.find(HP + "run")
            font = fonts.get(run.get("charPrIDRef") if run is not None else None) or 0
            if not font:
                continue
            cell_font = max(cell_font, font)
            text = "".join(t.text or "" for t in text_nodes(p))
            width = sum(font if ord(ch) > 0x2E80 else font / 2 for ch in text)
            needed += max(1, math.ceil(width / inner_width))

        if not cell_font:
            continue
        advance = round(cell_font * LINE_SPACING)
        capacity = max(1, round(inner_height / advance))
        if needed > capacity:
            problems.append(
                f"r{row}c{col} ({name}): {needed}줄이 필요한데 {capacity}줄만 들어갑니다 "
                f"— {needed - capacity}줄 줄여야 표가 밀리지 않습니다"
            )
    return problems


def check_against_draft(cells, draft: dict) -> list[str]:
    expected = {
        CELL["week"]: format_week(draft),
        CELL["author"]: f"{draft['author']} (인)",
    }
    if draft.get("team"):
        expected[CELL["team"]] = draft["team"]
    if draft.get("risk_students"):
        expected[CELL["risk"]] = draft["risk_students"]
    for name in NARRATIVE:
        expected[CELL[name]] = "\n".join(lines_or_empty(draft, f"{name}_lines"))

    problems = []
    for (row, col), want in expected.items():
        got = cell_text(cells[(row, col)], deep=False)
        if got != want:
            problems.append(f"r{row}c{col}: 기대 {want!r} / 실제 {got!r}")

    if draft.get("progress"):
        want = [f"{int(v)}명" for v in draft["progress"]]
        got = progress_values(cells)
        if got != want:
            problems.append(f"진도율 분포가 초안과 다릅니다: 기대 {want} / 실제 {got}")

    for name in NARRATIVE:
        if not cell_text(cells[CELL[name]], deep=False).strip():
            problems.append(f"{name}이(가) 비어 있습니다 (내역이 없다면 '{EMPTY}' 명시)")

    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description="주간 업무일지 hwpx 검사")
    ap.add_argument("path")
    ap.add_argument("--against", help="대조할 초안 JSON")
    ap.add_argument("--template", help="잔존 검사에 쓸 양식 경로")
    ap.add_argument(
        "--allow-overflow",
        action="store_true",
        help="셀 높이 초과를 경고로만 알리고 통과시킨다 (표가 아래로 밀릴 수 있음)",
    )
    ap.add_argument(
        "--allow-stale",
        action="store_true",
        help="양식과 같은 값이 남아 있어도 통과시킨다 (지난 주 값이 맞다고 확인한 경우)",
    )
    args = ap.parse_args()

    cells = weekly_cells(args.path)
    draft = json.loads(Path(args.against).read_text(encoding="utf-8")) if args.against else None

    overflow = check_overflow(args.path, cells)
    if args.allow_overflow and overflow:
        print(f"경고 — 셀 높이 초과 {len(overflow)}건 (표가 아래로 밀릴 수 있습니다)")
        for item in overflow:
            print(f"  ! {item}")
        overflow = []

    stale = check_stale(
        args.path, Path(args.template) if args.template else default_template(), draft
    )
    if args.allow_stale and stale:
        print(f"경고 — 양식과 같은 값 {len(stale)}건")
        for item in stale:
            print(f"  ! {item}")
        stale = []

    problems = check_placeholders(cells) + check_colors(args.path, cells) + overflow + stale
    if draft is not None:
        problems += check_against_draft(cells, draft)

    if problems:
        print(f"검사 실패 — {len(problems)}건")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)

    print(f"검사 통과: {args.path}")


if __name__ == "__main__":
    main()
