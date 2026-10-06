#!/bin/bash
# 터미널에서 한 번에 일지를 만든다. claude -p 를 손으로 조립하지 않아도 되게 하는 래퍼.
#
#   scripts/log.sh                          notes/<오늘>.md 로 hwpx까지
#   scripts/log.sh --date 2026-07-30        날짜 지정
#   echo "..." | scripts/log.sh             stdin 으로 내용 전달
#   scripts/log.sh "김OO git 오류 답변..."   인자로 직접 전달
#
# config.toml에 [drive]가 있으면 검사를 통과한 뒤 구글 드라이브 제출 폴더에도 올린다.
# 마지막 줄에 생성된 파일 경로만 남기므로 open "$(scripts/log.sh)" 가 된다.
set -uo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT" || exit 1

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if ! command -v claude >/dev/null 2>&1; then
  echo "claude 명령을 찾지 못했습니다." >&2
  exit 1
fi

DATE="$(date +%F)"
TEXT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --date) DATE="${2:-}"; shift 2 ;;
    --date=*) DATE="${1#*=}"; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) TEXT="${TEXT:+$TEXT }$1"; shift ;;
  esac
done

# 파이프로 들어온 내용이 있으면 인자보다 우선한다.
if [ ! -t 0 ]; then
  STDIN="$(cat)"
  [ -n "$STDIN" ] && TEXT="$STDIN"
fi

# 셋 다 없으면 스킬이 물어볼 상대가 없다. 여기서 먼저 걸러 준다.
if [ -z "$TEXT" ] && [ ! -f "$PROJECT/notes/$DATE.md" ]; then
  echo "입력이 없습니다. 다음 중 하나가 필요합니다:" >&2
  echo "  - 인자:  scripts/log.sh \"오늘 있었던 일...\"" >&2
  echo "  - stdin: echo \"...\" | scripts/log.sh" >&2
  echo "  - 메모:  notes/$DATE.md 작성" >&2
  exit 1
fi

PROMPT="/daily-log --yes --date $DATE"
[ -n "$TEXT" ] && PROMPT="$PROMPT $TEXT"

# 비대화형은 권한 질문에 답할 수 없다. .claude/settings.json은 workspace를 신뢰해야
# 적용되므로(신뢰 다이얼로그는 -p에서 뜨지 않는다) 필요한 것만 여기서 직접 넘긴다.
#
# 파일 쓰기는 Write(...)가 아니라 Edit(...)로 적는다. 파일 권한 검사는 Edit 규칙만 보고,
# 그 규칙이 Write를 포함한 모든 편집 도구를 덮는다. Write(...)로 적으면 조용히 무시된다.
ALLOWED=(
  "Bash(python3 tools/fill_hwpx.py:*)"
  "Bash(python3 tools/verify_hwpx.py:*)"
  "Bash(python3 tools/fetch_discord.py:*)"
  "Bash(python3 tools/upload_drive.py:*)"
  "Read"
  "Edit(notes/**)"
  "Edit(drafts/**)"
  "Edit(style/**)"
  "Edit(config.toml)"
)

if ! OUTPUT="$(claude -p "$PROMPT" --allowedTools "${ALLOWED[@]}" 2>&1)"; then
  echo "$OUTPUT" >&2
  echo "일지 생성에 실패했습니다." >&2
  exit 1
fi

# 스킬이 마지막 줄에 파일 경로만 남기기로 되어 있다. 그게 아니면 전문을 보여준다.
LAST="$(printf '%s' "$OUTPUT" | tail -1)"
if [ ! -f "$LAST" ]; then
  echo "$OUTPUT" >&2
  echo "생성된 파일을 찾지 못했습니다. out/ 을 확인하세요." >&2
  exit 1
fi

echo "$LAST"

# 드라이브 링크는 앞줄에 섞여 있다. 마지막 줄 계약을 건드리지 않으려고 grep으로 집는다.
# stdout은 경로 전용이라 open "$(scripts/log.sh)" 가 계속 통해야 한다.
DRIVE="$(printf '%s\n' "$OUTPUT" | grep -o 'https://drive\.google\.com/[^ )"]*' | tail -1)"
if [ -n "$DRIVE" ]; then
  echo "드라이브: $DRIVE" >&2
elif grep -q '^\[drive\]' "$PROJECT/config.toml" 2>/dev/null; then
  # 파일은 생겼지만 제출은 안 된 상태다. 조용히 통과시키면 안 올라간 걸 모른다.
  echo "$OUTPUT" >&2
  echo "드라이브에 올라가지 않았습니다. 위 출력을 확인하고 필요하면 직접 올리세요:" >&2
  echo "  python3 tools/upload_drive.py \"$LAST\"" >&2
  exit 2
fi
