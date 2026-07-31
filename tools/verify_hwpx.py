#!/usr/bin/env python3
"""산출 hwpx가 제출 가능한 상태인지 검사한다 (AC-7).

  python tools/verify_hwpx.py out/일지_2026-07-31.hwpx
  python tools/verify_hwpx.py out/일지_2026-07-31.hwpx --against drafts/2026-07-31.json

--against를 주면 초안 값이 지정한 셀에 그대로 들어갔는지까지 대조한다 (라운드트립 검사).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fill_hwpx import CELL, EMPTY, format_date, lines_or_empty
from hwpx import BLACK, HH, HP, cell_text, find_daily_table, load_header, load_section, table_cells

# 양식에 원래 들어 있는 안내문구. 하나라도 남아 있으면 그 셀은 채워지지 않은 것이다.
# '[문의 1]' 같은 대괄호 라벨은 채워진 결과에도 정상적으로 들어가므로 여기 넣지 않는다.
PLACEHOLDERS = [
    "작성해 주세요",
    "2026. 00. 00.",
    "(0요일)",
    "총 ()건",
]

# 라벨만 있고 내용이 비어 있는 줄. 양식 잔존물이자 미작성 상태다.
EMPTY_LABELS = ["조치 내용:", "가이드 내용:"]

# 한글 기본 줄 간격(글자 크기의 160%). 원본 배치값 800 * 1.6 = 1280과 일치한다.
LINE_SPACING = 1.6


def check_placeholders(cells) -> list[str]:
    problems = []
    for (row, col), tc in sorted(cells.items()):
        text = cell_text(tc)
        for token in PLACEHOLDERS:
            if token in text:
                problems.append(f"r{row}c{col}: 안내문구 잔존 — {token!r}")
        for line in text.split("\n"):
            if line.strip() in EMPTY_LABELS:
                problems.append(f"r{row}c{col}: 라벨만 있고 내용이 비었습니다 — {line.strip()!r}")
    return problems


def check_colors(path: str, cells) -> list[str]:
    """채운 셀의 글자가 검은색인지 본다.

    양식의 안내문구는 파란 글씨라, 문단을 복제해 내용을 채우면 결과물도 파랗게 나온다.
    눈으로 열어보기 전에는 드러나지 않는 종류의 오류라 기계로 잡는다.
    """
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
    """셀 높이를 넘는 내용이 있는지 본다.

    양식은 셀 높이가 고정이라 내용이 넘치면 표가 아래로 밀리면서 한 장짜리 서식이
    깨진다. 한글이 원본에 남긴 배치값을 보면 글자 크기 800(8pt)에 줄 간격은 그 160%인
    1280이고, 본문 폭은 셀 너비에서 좌우 여백을 뺀 값이다. 한글 글자는 폭이 글자 크기와
    같고 영숫자는 그 절반이라는 점을 이용해 필요한 줄 수를 어림한다.
    """
    fonts = {
        cp.get("id"): int(cp.get("height") or 0)
        for cp in load_header(path).iter(HH + "charPr")
    }

    problems = []
    for name, (row, col) in CELL.items():
        tc = cells[(row, col)]
        size, margin = tc.find(HP + "cellSz"), tc.find(HP + "cellMargin")
        inner_width = int(size.get("width")) - int(margin.get("left")) - int(margin.get("right"))
        inner_height = int(size.get("height")) - int(margin.get("top")) - int(margin.get("bottom"))

        needed, cell_font = 0, 0
        for p in tc.iter(HP + "p"):
            run = p.find(HP + "run")
            font = fonts.get(run.get("charPrIDRef") if run is not None else None) or 0
            if not font:
                continue
            cell_font = max(cell_font, font)
            text = "".join(t.text or "" for t in p.iter(HP + "t"))
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
    counts = draft.get("counts") or {}
    expected = {
        CELL["date"]: format_date(draft["date"]),
        CELL["author"]: f"{draft['author']} (인)",
        CELL["summary"]: draft["summary"],
        CELL["first_response_count"]: f"총 {int(counts.get('first_response', 0))}건",
        CELL["learning_support_count"]: f"총 {int(counts.get('learning_support', 0))}건",
        CELL["guidance_count"]: f"총 {int(counts.get('guidance', 0))}건",
        CELL["inquiry"]: "\n".join(lines_or_empty(draft, "inquiry_lines")),
        CELL["counseling"]: "\n".join(lines_or_empty(draft, "counseling_lines")),
        CELL["guidance"]: "\n".join(lines_or_empty(draft, "guidance_lines")),
        CELL["handover"]: "\n".join(lines_or_empty(draft, "handover_lines")),
    }

    problems = []
    for (row, col), want in expected.items():
        got = cell_text(cells[(row, col)])
        if got != want:
            problems.append(f"r{row}c{col}: 기대 {want!r} / 실제 {got!r}")

    # AC-5: 오늘 업무 요약은 한 문장이어야 한다.
    summary = draft["summary"].strip()
    if summary.count(".") > 1 or "\n" in summary:
        problems.append(f"요약이 한 문장이 아닙니다: {summary!r}")

    # AC-6: 상세 셀은 비어 있으면 안 된다. 내역이 없는 날은 '해당 없음'이 정상값이다.
    for name in ("inquiry", "counseling", "guidance"):
        if not cell_text(cells[CELL[name]]).strip():
            problems.append(f"{name} 상세가 비어 있습니다 (내역이 없다면 '{EMPTY}' 명시)")

    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description="일일 업무일지 hwpx 검사")
    ap.add_argument("path")
    ap.add_argument("--against", help="대조할 초안 JSON")
    ap.add_argument(
        "--allow-overflow",
        action="store_true",
        help="셀 높이 초과를 경고로만 알리고 통과시킨다 (표가 아래로 밀릴 수 있음)",
    )
    args = ap.parse_args()

    root = load_section(args.path)
    cells = table_cells(find_daily_table(root))

    overflow = check_overflow(args.path, cells)
    if args.allow_overflow and overflow:
        print(f"경고 — 셀 높이 초과 {len(overflow)}건 (표가 아래로 밀릴 수 있습니다)")
        for item in overflow:
            print(f"  ! {item}")
        overflow = []

    problems = check_placeholders(cells) + check_colors(args.path, cells) + overflow
    if args.against:
        draft = json.loads(Path(args.against).read_text(encoding="utf-8"))
        problems += check_against_draft(cells, draft)

    if problems:
        print(f"검사 실패 — {len(problems)}건")
        for p in problems:
            print(f"  - {p}")
        raise SystemExit(1)

    print(f"검사 통과: {args.path}")


if __name__ == "__main__":
    main()
