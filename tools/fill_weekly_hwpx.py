#!/usr/bin/env python3
"""초안 JSON을 붙임2 주간 업무일지 양식에 채워 hwpx 파일을 만든다.

  python tools/fill_weekly_hwpx.py --in drafts/week-2026-07-27.json

일일 양식과 같은 원칙이다. 판단(집계·문체)은 Claude가 하고 이 스크립트는 받은 값을
정해진 셀에 넣기만 한다. 여기서는 어떤 내용도 생성하지 않는다.

일일 양식과 다른 점이 둘 있다.
- 출석률·미션 진도율·이탈 위험 교육생은 디스코드나 일일 초안이 아니라 운영팀 시트에서
  온다. 초안 JSON에 값이 실려 오지 않으면 그 칸은 손대지 않고 양식 그대로 둔다.
- 미션 진도율은 셀 안에 표가 또 들어 있다(0%~100% 12칸 + 시험 + TP).
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
    find_weekly_table,
    load_header,
    load_section,
    nested_table,
    save,
    set_cell,
    set_cell_lines,
    set_cell_parts,
    set_cell_texts,
    table_cells,
    take_picture,
)

# 붙임2 표(11행 x 5열)의 실측 좌표. 양식이 개정되면 여기만 고치면 된다.
CELL = {
    "week": (1, 1),
    "author": (1, 4),
    "team": (2, 1),
    "attendance": (4, 2),
    "progress": (5, 2),  # 셀 안에 진도율 분포표가 들어 있다
    "risk": (6, 2),
    "improvement": (7, 1),
    "student_issue": (8, 1),
    "handover": (9, 1),
    "next_week": (10, 1),
}

# 진도율 분포표(2행 x 14열)의 머리글. 값은 아랫줄(r1)에 들어간다.
PROGRESS_COLUMNS = [
    "0%", "9%", "18%", "27%", "36%", "45%", "54%",
    "63%", "72%", "81%", "90%", "100%", "시험", "TP",
]
PROGRESS_ROW = 1

# 서술 4칸. 양식이 '- ' 글머리를 쓰므로 초안의 줄을 그대로 넣는다.
NARRATIVE = ["improvement", "student_issue", "handover", "next_week"]

REQUIRED = ["week_start", "author"]
EMPTY = "해당 없음"

# 운영팀에서 받은 붙임2에는 서명과 교육생 실명이 이미 채워져 있어 저장소에 올리지 않는다.
BLANK_TEMPLATE = Path("templates/weekly.hwpx")
SIGNED_TEMPLATE = Path("templates/weekly.signed.hwpx")


def default_template() -> Path:
    return SIGNED_TEMPLATE if SIGNED_TEMPLATE.exists() else BLANK_TEMPLATE


def monday(value: str) -> dt.date:
    """주 시작일. 어느 요일을 줘도 그 주 월요일로 맞춘다."""
    d = dt.date.fromisoformat(value)
    return d - dt.timedelta(days=d.weekday())


def week_range(draft: dict) -> tuple[dt.date, dt.date]:
    """작성 주간은 월요일부터 일요일까지다. 집계는 평일만 보더라도 표기는 양식을 따른다."""
    start = monday(draft["week_start"])
    return start, start + dt.timedelta(days=6)


def format_week(draft: dict) -> str:
    start, end = week_range(draft)
    return f"{start.year}. {start.month:02d}. {start.day:02d}. ~ {end.year}. {end.month:02d}. {end.day:02d}."


def require(draft: dict) -> None:
    missing = [k for k in REQUIRED if not draft.get(k)]
    if missing:
        raise SystemExit(f"초안에 필수 항목이 없습니다: {', '.join(missing)}")


def default_out(draft: dict) -> Path:
    """제출용 파일명. 운영팀이 요구하는 형식이라 임의로 바꾸지 않는다."""
    require(draft)
    start, end = week_range(draft)
    author = str(draft["author"]).strip().replace("/", "")
    span = f"{start.month:02d}{start.day:02d}~{end.month:02d}{end.day:02d}"
    # macOS가 넘겨준 자모 분리형(NFD) 이름은 Windows에서 ㅋㅗㄷㅣ처럼 깨져 보인다
    name = f"[코디세이]{span}_{author}_퍼실리테이터_주간일지.hwpx"
    return Path("out") / unicodedata.normalize("NFC", name)


def lines_or_empty(draft: dict, key: str) -> list[str]:
    lines = [line.strip() for line in draft.get(key) or [] if line and line.strip()]
    return lines or [EMPTY]


def set_author(tc, author: str, palette: CharPrPalette) -> None:
    """작성자 칸을 '<이름> (인)'으로 채우되 서명 도장은 살려 둔다. 일일 양식과 같은 처리다."""
    signature = take_picture(tc)
    parts = [f"{author} ("] + ([signature] if signature is not None else []) + ["인)"]
    set_cell_parts(tc, parts, palette)


def set_attendance(tc, draft: dict, palette: CharPrPalette) -> None:
    """출석률 칸. 운영팀 메모가 글자 사이에 닻을 내리고 있어 셀을 다시 만들지 않는다.

    글자 조각 셋으로 이루어져 있다: 달성자 비율 문장 / '출결률 평균' 라벨 / ' : N%'.
    가운데 라벨은 양식의 것이므로 건드리지 않는다.
    """
    rate = draft.get("attendance_rate")
    average = draft.get("attendance_average")
    if rate is None and average is None:
        return

    texts: list[str | None] = [None, None, None]
    if rate is not None:
        texts[0] = f"1. {rate}% (20시간 이상 달성자 비율)"
    if average is not None:
        texts[2] = f" : {average}%"
    set_cell_texts(tc, texts, palette)


def set_progress(tc, draft: dict, palette: CharPrPalette) -> None:
    """미션 진도율 분포표. 구간별 인원을 아랫줄에 넣는다."""
    progress = draft.get("progress")
    if not progress:
        return

    if len(progress) != len(PROGRESS_COLUMNS):
        raise SystemExit(
            f"progress는 {len(PROGRESS_COLUMNS)}칸이어야 합니다 "
            f"({', '.join(PROGRESS_COLUMNS)}). {len(progress)}개를 받았습니다."
        )

    inner = nested_table(tc)
    if inner is None:
        raise SystemExit("진도율 칸에서 분포표를 찾지 못했습니다. 양식 파일을 확인하세요.")

    cells = table_cells(inner)
    for column, value in enumerate(progress):
        set_cell(cells[(PROGRESS_ROW, column)], f"{int(value)}명", palette)


def fill(draft: dict, template: Path, out: Path) -> Path:
    require(draft)

    root = load_section(template)
    header = load_header(template)
    palette = CharPrPalette(header)
    cells = table_cells(find_weekly_table(root))

    def cell(name):
        return cells[CELL[name]]

    set_cell(cell("week"), format_week(draft), palette)
    set_author(cell("author"), draft["author"], palette)
    if draft.get("team"):
        set_cell(cell("team"), draft["team"], palette)

    set_attendance(cell("attendance"), draft, palette)
    set_progress(cell("progress"), draft, palette)
    if draft.get("risk_students"):
        set_cell(cell("risk"), draft["risk_students"], palette)

    for key in NARRATIVE:
        set_cell_lines(cell(key), lines_or_empty(draft, f"{key}_lines"), palette)

    parts = {SECTION: root}
    if palette.modified:  # 검은색 대체 서식을 새로 만들었으면 header.xml도 같이 써야 한다
        parts[HEADER] = header

    save(template, out, parts)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="주간 업무일지 hwpx 생성")
    ap.add_argument("--in", dest="src", required=True, help="초안 JSON 경로")
    ap.add_argument(
        "--template",
        help=f"양식 경로 (기본: {SIGNED_TEMPLATE}가 있으면 그것, 없으면 {BLANK_TEMPLATE})",
    )
    ap.add_argument(
        "--out",
        help="출력 경로 (기본: out/[코디세이]MMDD~MMDD_<이름>_퍼실리테이터_주간일지.hwpx)",
    )
    args = ap.parse_args()

    draft = json.loads(Path(args.src).read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else default_out(draft)
    print(fill(draft, Path(args.template) if args.template else default_template(), out))


if __name__ == "__main__":
    main()
