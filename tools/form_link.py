#!/usr/bin/env python3
"""확정된 일지 초안에서 활동기록부 구글 폼 프리필 링크를 만든다.

  python3 tools/form_link.py --in drafts/2026-08-13.json
  python3 tools/form_link.py --in drafts/2026-08-13.json --open   # 기본 브라우저로 띄운다
  python3 tools/form_link.py --in <초안> --schema <스키마.json>    # 폼을 조회하지 않는다

폼 주소는 코드가 아니라 config.toml의 [form]에서 읽는다. 폼이 바뀌면 그 한 줄만 고친다.

**제출하지 않는다.** 답이 미리 채워진 링크를 만들 뿐이고 제출 버튼은 사람이 누른다.
드라이브 업로드는 `rclone copyto`라 다시 올려도 같은 파일을 덮어쓰지만, 폼 응답은 누를 때마다
새로 쌓인다. 자동 제출은 한 번의 실수가 되돌릴 수 없는 중복 응답이 되므로 여기서 멈춘다.

보기 문자열 검사가 이 스크립트의 핵심이다. 구글 폼은 프리필 값이 보기와 다르면 오류를 내지 않고
그 값을 조용히 버린다 — 오타 하나로 필수 문항이 빈 채 제출된다. 그래서 링크를 만들기 전에
살아 있는 폼 정의에 대고 맞춰 본다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "form_schema.json"

# 폼 정의는 viewform HTML 안에 이 전역 변수로 통째로 실려 온다.
LOAD_DATA = re.compile(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\]);", re.S)
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# 구글 폼 문항 타입 코드. 0=단답형, 1=장문형, 4=체크박스, 6=안내문(입력 없음)
TYPE_TEXT = (0, 1)
TYPE_CHECKBOX = 4

OTHER_VALUE = "__other_option__"
BROWSER = "open" if sys.platform == "darwin" else "xdg-open"

# 초안의 form 블록 키 → 폼 문항. 값은 사람이 읽을 이름이다.
FIELDS = {
    "activities": "주요 활동(체크박스)",
    "notes": "기타 특이 사항(체크박스)",
    "field_note": "서술형",
}
CHECKBOX_FIELDS = ("activities", "notes")


# --- 설정 -------------------------------------------------------------------

def load_form_config(path: Path) -> dict:
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8")).get("form", {})


def base_url(value: str) -> str:
    """설정값에서 질의 문자열을 떼어 낸다. 프리필 링크를 그대로 붙여넣어도 되게 하기 위함이다."""
    text = str(value).strip()
    if not text.startswith(("http://", "https://")):
        raise SystemExit(
            f"폼 주소를 알아볼 수 없습니다: {value!r}\n"
            "폼을 연 뒤 주소창을 그대로 붙여넣으세요 "
            "(https://docs.google.com/forms/d/e/.../viewform 형태)."
        )
    parsed = urllib.parse.urlparse(text)
    return urllib.parse.urlunparse(parsed._replace(query="", fragment=""))


# --- 폼 정의 ----------------------------------------------------------------

def parse_schema(html: str, url: str) -> dict:
    """viewform HTML에서 문항·보기 목록을 뽑아 우리 형식으로 줄인다."""
    found = LOAD_DATA.search(html)
    if not found:
        raise SystemExit(
            "폼 정의를 찾지 못했습니다. 로그인이 필요한 폼이거나 주소가 잘못됐을 수 있습니다.\n"
            f"  {url}\n"
            "브라우저에서 그 주소가 폼으로 열리는지 먼저 확인하세요."
        )
    try:
        data = json.loads(found.group(1))
        body = data[1]
        items = body[1] or []
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        raise SystemExit(f"폼 정의를 해석하지 못했습니다: {exc}")

    questions = []
    for item in items:
        kind = item[3] if len(item) > 3 else None
        entries = item[4] if len(item) > 4 else None
        if kind not in (*TYPE_TEXT, TYPE_CHECKBOX) or not entries:
            continue  # 안내문·구분선처럼 답을 받지 않는 항목
        entry = entries[0]
        raw_options = entry[1] or []
        questions.append({
            "entry": str(entry[0]),
            "title": item[1] or "",
            "type": "checkbox" if kind == TYPE_CHECKBOX else "text",
            "required": bool(entry[2]) if len(entry) > 2 else False,
            # 보기 목록의 마지막에 붙는 '기타'는 라벨이 비어 있고 플래그로만 구분된다
            "options": [o[0] for o in raw_options if not (len(o) > 4 and o[4])],
            "has_other": any(len(o) > 4 and o[4] for o in raw_options),
        })

    return {"url": url, "title": body[8] if len(body) > 8 else "", "questions": questions}


def fetch_schema(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        html = response.read().decode("utf-8", "replace")
    return parse_schema(html, url)


def resolve_schema(schema_path: str | None, url: str) -> dict:
    """--schema > 살아 있는 폼 > 캐시. 폼이 바뀌면 다음 실행에 바로 반영되게 조회를 앞에 둔다."""
    if schema_path:
        path = Path(schema_path)
        if not path.is_file():
            raise SystemExit(f"스키마 파일이 없습니다: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    try:
        schema = fetch_schema(url)
    except (urllib.error.URLError, OSError) as exc:
        if CACHE.is_file():
            print(f"폼 조회 실패({exc}) — 캐시된 정의를 씁니다: {CACHE}", file=sys.stderr)
            return json.loads(CACHE.read_text(encoding="utf-8"))
        raise SystemExit(
            f"폼을 조회하지 못했고 캐시도 없습니다: {exc}\n"
            f"  {url}\n"
            "네트워크를 확인하거나 --schema 로 저장해 둔 정의를 넘기세요."
        )

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return schema


FIELD_NOTE_TITLE_HINT = "오늘 현장의 온도"


def pick_questions(schema: dict) -> dict:
    """문항을 초안의 form 키에 붙인다. 폼 구성이 바뀌면 조용히 어긋나지 말고 여기서 멈춘다.

    서술형 문항은 제목에 FIELD_NOTE_TITLE_HINT가 들어간 것 하나만 쓴다. 그 외 서술형
    (예: 자동 입력되는 퍼실리테이터 ID)은 우리가 채울 대상이 아니므로 그냥 둔다.
    """
    checkboxes = [q for q in schema["questions"] if q["type"] == "checkbox"]
    texts = [q for q in schema["questions"] if q["type"] == "text"]
    field_notes = [q for q in texts if FIELD_NOTE_TITLE_HINT in q["title"]]

    if len(checkboxes) != 2 or len(field_notes) != 1:
        listing = "\n".join(f"  - [{q['type']}] {q['title']}" for q in schema["questions"]) or "  (없음)"
        raise SystemExit(
            "폼 구성이 예상과 다릅니다. 체크박스 2문항과 "
            f"제목에 '{FIELD_NOTE_TITLE_HINT}'가 들어간 서술형 1문항을 기대했으나 "
            f"체크박스 {len(checkboxes)}개, 해당 서술형 {len(field_notes)}개를 찾았습니다:\n"
            f"{listing}\n"
            "운영팀이 폼을 고쳤다면 tools/form_link.py의 문항 연결과 "
            ".claude/skills/daily-log/SKILL.md의 보기 매핑을 함께 손봐야 합니다."
        )

    return {"activities": checkboxes[0], "notes": checkboxes[1], "field_note": field_notes[0]}


# --- 검사 -------------------------------------------------------------------

def validate(form: dict, questions: dict, exclusive: list[str]) -> list[str]:
    """구글이 조용히 버릴 값을 미리 잡는다. 문제를 모아서 한 번에 돌려준다."""
    problems = []

    for key in CHECKBOX_FIELDS:
        question = questions[key]
        chosen = form.get(key) or []
        other = str(form.get(f"{key}_other") or "").strip()

        if not isinstance(chosen, list):
            problems.append(f"{FIELDS[key]}: {key}는 목록이어야 합니다 (지금은 {type(chosen).__name__}).")
            continue

        unknown = [c for c in chosen if c not in question["options"]]
        if unknown:
            valid = "\n".join(f"    - {o}" for o in question["options"])
            problems.append(
                f"{FIELDS[key]}: 폼에 없는 보기입니다 — {', '.join(repr(u) for u in unknown)}\n"
                f"  구글 폼은 보기와 다른 값을 오류 없이 버립니다. 아래 중에서 고르거나 "
                f"{key}_other 에 직접 쓰세요:\n{valid}"
            )

        if other and not question["has_other"]:
            problems.append(f"{FIELDS[key]}: 이 문항에는 '기타' 칸이 없어 {key}_other 를 쓸 수 없습니다.")

        if question["required"] and not chosen and not other:
            problems.append(f"{FIELDS[key]}: 필수 문항인데 비어 있습니다.")

        picked = set(chosen)
        for value in exclusive:
            if value in picked and (len(picked) > 1 or other):
                problems.append(
                    f"{FIELDS[key]}: '{value}'는 단독으로만 선택합니다. "
                    f"지금 함께 선택된 것 — {', '.join(sorted(picked - {value}))}"
                    f"{' / 기타: ' + other if other else ''}"
                )

    text_question = questions["field_note"]
    note = form.get("field_note")
    if not isinstance(note, str):
        problems.append(f"{FIELDS['field_note']}: field_note는 문자열이어야 합니다.")
    elif text_question["required"] and not note.strip():
        problems.append(f"{FIELDS['field_note']}: 필수 문항인데 비어 있습니다.")

    return problems


# --- 링크 -------------------------------------------------------------------

def build_url(url: str, form: dict, questions: dict) -> str:
    params = [("usp", "pp_url")]

    for key in CHECKBOX_FIELDS:
        entry = questions[key]["entry"]
        for option in form.get(key) or []:
            params.append((f"entry.{entry}", option))
        other = str(form.get(f"{key}_other") or "").strip()
        if other:
            # 기타는 값 자리에 표식을 넣고 실제 텍스트를 짝 파라미터로 보낸다
            params.append((f"entry.{entry}", OTHER_VALUE))
            params.append((f"entry.{entry}.other_option_response", other))

    params.append((f"entry.{questions['field_note']['entry']}", form["field_note"]))
    return f"{url}?{urllib.parse.urlencode(params)}"


def summarize(form: dict, questions: dict) -> str:
    lines = []
    for key in CHECKBOX_FIELDS:
        chosen = list(form.get(key) or [])
        other = str(form.get(f"{key}_other") or "").strip()
        if other:
            chosen.append(f"기타: {other}")
        lines.append(f"{questions[key]['title']}: " + (" / ".join(chosen) or "(없음)"))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="일지 초안에서 활동기록부 폼 프리필 링크 생성")
    ap.add_argument("--in", dest="src", required=True, help="초안 JSON 경로")
    ap.add_argument("--url", help="폼 주소. config.toml의 [form]을 덮어쓴다")
    ap.add_argument("--schema", help="저장해 둔 폼 정의 JSON. 폼을 조회하지 않는다")
    ap.add_argument("--config", default=str(ROOT / "config.toml"))
    ap.add_argument("--open", dest="open_browser", action="store_true",
                    help="만든 링크를 기본 브라우저로 띄운다")
    args = ap.parse_args()

    source = Path(args.src)
    if not source.is_file():
        raise SystemExit(f"초안이 없습니다: {source}")
    draft = json.loads(source.read_text(encoding="utf-8"))

    config = load_form_config(Path(args.config))
    configured = args.url or config.get("url")
    if not configured:
        # 설정하지 않은 것은 실패가 아니다. 폼 없이 HWPX까지만 쓰는 사용법을 남겨 둔다.
        print("폼 링크 건너뜀 ([form] 미설정) — config.toml에 [form]을 추가하면 링크를 만듭니다.")
        return

    form = draft.get("form")
    if not isinstance(form, dict):
        raise SystemExit(
            f"초안에 form 블록이 없습니다: {source}\n"
            "일지 내용에서 폼 답변을 판단해 아래 형태로 추가한 뒤 다시 실행하세요.\n"
            '  "form": {\n'
            '    "activities": [], "activities_other": "",\n'
            '    "notes": [], "notes_other": "",\n'
            '    "field_note": ""\n'
            "  }"
        )

    url = base_url(configured)
    questions = pick_questions(resolve_schema(args.schema, url))

    problems = validate(form, questions, list(config.get("exclusive") or []))
    if problems:
        raise SystemExit(
            f"폼 답변을 검사하지 못했습니다 ({len(problems)}건). "
            f"{source}의 form 블록을 고쳐 다시 실행하세요.\n\n"
            + "\n\n".join(f"- {p}" for p in problems)
        )

    link = build_url(url, form, questions)

    if args.open_browser:
        opened = subprocess.run([BROWSER, link], capture_output=True, text=True)
        if opened.returncode != 0:
            print(f"브라우저를 띄우지 못했습니다 ({BROWSER}). 아래 링크를 직접 여세요.",
                  file=sys.stderr)

    print(summarize(form, questions), file=sys.stderr)
    print(link)


if __name__ == "__main__":
    main()
