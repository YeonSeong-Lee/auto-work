#!/usr/bin/env python3
"""초안 JSON을 붙임1 일일 업무일지 양식에 채워 hwpx 파일을 만든다.

  python tools/fill_hwpx.py --in drafts/2026-07-31.json

판단(분류·요약·문체)은 Claude가 하고, 이 스크립트는 받은 값을 정해진 셀에 넣기만 한다.
결정론적으로 동작해야 하므로 여기서는 어떤 내용도 생성하지 않는다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import unicodedata
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
    set_cell_parts,
    table_cells,
    take_picture,
)

WEEKDAYS = "월화수목금토일"

# 붙임1 표(13행 x 7열)의 실측 좌표. 양식이 개정되면 여기만 고치면 된다.
CELL = {
    "date": (1, 1),
    "author": (1, 6),
    "team": (2, 1),
    "summary": (3, 1),
    "operation_note": (5, 4),
    "operation_status": (5, 3),
    "first_response_count": (6, 4),
    "first_response_status": (6, 3),
    "learning_support_count": (7, 4),
    "learning_support_status": (7, 3),
    "guidance_count": (8, 4),
    "guidance_status": (8, 3),
    "inquiry": (9, 1),
    "counseling": (10, 1),
    "guidance": (11, 1),
    "handover": (12, 1),
}

REQUIRED = ["date", "author", "summary"]
EMPTY = "해당 없음"

# 서명이 박힌 양식은 개인 정보라 저장소에 올리지 않는다. 있으면 그걸, 없으면 빈 양식을 쓴다.
BLANK_TEMPLATE = Path("templates/daily.hwpx")
SIGNED_TEMPLATE = Path("templates/daily.signed.hwpx")


def default_template() -> Path:
    return SIGNED_TEMPLATE if SIGNED_TEMPLATE.exists() else BLANK_TEMPLATE


def format_date(value: str) -> str:
    d = dt.date.fromisoformat(value)
    return f"{d.year}. {d.month:02d}. {d.day:02d}. ({WEEKDAYS[d.weekday()]}요일)"


def require(draft: dict) -> None:
    missing = [k for k in REQUIRED if not draft.get(k)]
    if missing:
        raise SystemExit(f"초안에 필수 항목이 없습니다: {', '.join(missing)}")


def default_out(draft: dict) -> Path:
    """제출용 파일명. 운영팀이 요구하는 형식이라 임의로 바꾸지 않는다."""
    require(draft)
    d = dt.date.fromisoformat(draft["date"])
    author = str(draft["author"]).strip().replace("/", "")
    stem = f"[코디세이]{d.month:02d}{d.day:02d}({WEEKDAYS[d.weekday()]})_{author}_퍼실리테이터 일일업무일지"
    # macOS가 넘겨준 자모 분리형(NFD) 이름은 Windows에서 ㅋㅗㄷㅣ처럼 깨져 보인다
    return Path("out") / unicodedata.normalize("NFC", f"{stem}.hwpx")


def lines_or_empty(draft: dict, key: str) -> list[str]:
    lines = [line.strip() for line in draft.get(key) or [] if line and line.strip()]
    return lines or [EMPTY]


def status_marks(draft: dict) -> dict[str, str]:
    """수행여부 열의 O/X. 운영지원은 상시 업무라 항상 O, 나머지는 건수로 판단한다."""
    counts = draft.get("counts") or {}
    marks = {"operation": "O"}
    for key in ("first_response", "learning_support", "guidance"):
        marks[key] = "O" if int(counts.get(key, 0)) > 0 else "X"
    return marks


def set_author(tc, author: str, palette: CharPrPalette) -> None:
    """작성자 칸을 '<이름> (인)'으로 채우되, 양식에 박혀 있던 서명 도장은 살려 둔다.

    서명은 '('와 '인)' 사이에 글자처럼 끼워져 있다. 셀을 통째로 갈아끼우면 같이 지워지므로
    먼저 떼어 두었다가 같은 자리에 다시 넣는다. 서명이 없는 양식이면 그냥 '(인)'이 된다.
    """
    signature = take_picture(tc)
    parts = [f"{author} ("] + ([signature] if signature is not None else []) + ["인)"]
    set_cell_parts(tc, parts, palette)


def fill(draft: dict, template: Path, out: Path) -> Path:
    require(draft)

    root = load_section(template)
    header = load_header(template)
    palette = CharPrPalette(header)
    cells = table_cells(find_daily_table(root))

    def cell(name):
        return cells[CELL[name]]

    counts = draft.get("counts") or {}

    set_cell(cell("date"), format_date(draft["date"]), palette)
    set_author(cell("author"), draft["author"], palette)
    set_cell(cell("team"), draft.get("team", ""), palette)
    set_cell(cell("summary"), draft["summary"], palette)
    set_cell(cell("operation_note"), draft.get("operation_note", ""), palette)

    for key in ("first_response", "learning_support", "guidance"):
        set_cell(cell(f"{key}_count"), f"총 {int(counts.get(key, 0))}건", palette)

    for key, mark in status_marks(draft).items():
        set_cell(cell(f"{key}_status"), mark, palette)

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
    ap.add_argument(
        "--template",
        help=f"양식 경로 (기본: {SIGNED_TEMPLATE}가 있으면 그것, 없으면 {BLANK_TEMPLATE})",
    )
    ap.add_argument(
        "--out",
        help="출력 경로 (기본: out/[코디세이]MMDD(요일)_<이름>_퍼실리테이터 일일업무일지.hwpx)",
    )
    args = ap.parse_args()

    draft = json.loads(Path(args.src).read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else default_out(draft)
    print(fill(draft, Path(args.template) if args.template else default_template(), out))


if __name__ == "__main__":
    main()
