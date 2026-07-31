#!/usr/bin/env python3
"""초안 JSON을 붙임1 일일 업무일지 양식에 채워 hwpx 파일을 만든다.

  python tools/fill_hwpx.py --in drafts/2026-07-31.json --out out/일지_2026-07-31.hwpx

판단(분류·요약·문체)은 Claude가 하고, 이 스크립트는 받은 값을 정해진 셀에 넣기만 한다.
결정론적으로 동작해야 하므로 여기서는 어떤 내용도 생성하지 않는다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hwpx import (
    HEADER,
    SECTION,
    CharPrPalette,
    find_daily_table,
    load_header,
    load_section,
    save,
    set_cell,
    set_cell_lines,
    table_cells,
)

WEEKDAYS = "월화수목금토일"

# 붙임1 표(13행 x 7열)의 실측 좌표. 양식이 개정되면 여기만 고치면 된다.
CELL = {
    "date": (1, 1),
    "author": (1, 6),
    "team": (2, 1),
    "summary": (3, 1),
    "operation_note": (5, 4),
    "first_response_count": (6, 4),
    "learning_support_count": (7, 4),
    "guidance_count": (8, 4),
    "inquiry": (9, 1),
    "counseling": (10, 1),
    "guidance": (11, 1),
    "handover": (12, 1),
}

REQUIRED = ["date", "author", "summary"]
EMPTY = "해당 없음"


def format_date(value: str) -> str:
    d = dt.date.fromisoformat(value)
    return f"{d.year}. {d.month:02d}. {d.day:02d}. ({WEEKDAYS[d.weekday()]}요일)"


def lines_or_empty(draft: dict, key: str) -> list[str]:
    lines = [line.strip() for line in draft.get(key) or [] if line and line.strip()]
    return lines or [EMPTY]


def fill(draft: dict, template: Path, out: Path) -> Path:
    missing = [k for k in REQUIRED if not draft.get(k)]
    if missing:
        raise SystemExit(f"초안에 필수 항목이 없습니다: {', '.join(missing)}")

    root = load_section(template)
    header = load_header(template)
    palette = CharPrPalette(header)
    cells = table_cells(find_daily_table(root))

    def cell(name):
        return cells[CELL[name]]

    counts = draft.get("counts") or {}

    set_cell(cell("date"), format_date(draft["date"]), palette)
    set_cell(cell("author"), f"{draft['author']} (인)", palette)
    set_cell(cell("team"), draft.get("team", ""), palette)
    set_cell(cell("summary"), draft["summary"], palette)
    set_cell(cell("operation_note"), draft.get("operation_note", ""), palette)

    for key in ("first_response", "learning_support", "guidance"):
        set_cell(cell(f"{key}_count"), f"총 {int(counts.get(key, 0))}건", palette)

    set_cell_lines(cell("inquiry"), lines_or_empty(draft, "inquiry_lines"), palette)
    set_cell_lines(cell("counseling"), lines_or_empty(draft, "counseling_lines"), palette)
    set_cell_lines(cell("guidance"), lines_or_empty(draft, "guidance_lines"), palette)
    set_cell_lines(cell("handover"), lines_or_empty(draft, "handover_lines"), palette)

    parts = {SECTION: root}
    if palette.modified:  # 검은색 대체 서식을 새로 만들었으면 header.xml도 같이 써야 한다
        parts[HEADER] = header

    save(template, out, parts)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="일일 업무일지 hwpx 생성")
    ap.add_argument("--in", dest="src", required=True, help="초안 JSON 경로")
    ap.add_argument("--template", default="templates/daily.hwpx")
    ap.add_argument("--out", help="출력 경로 (기본: out/일지_<날짜>.hwpx)")
    args = ap.parse_args()

    draft = json.loads(Path(args.src).read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else Path("out") / f"일지_{draft['date']}.hwpx"
    print(fill(draft, Path(args.template), out))


if __name__ == "__main__":
    main()
