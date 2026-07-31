#!/bin/bash
# 매일 정해진 시각에 일지 초안까지만 만들어 두고 알림을 띄운다.
# launchd가 부르는 진입점이라 PATH가 최소한이므로 여기서 직접 잡아준다.
set -uo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT" || exit 1

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
DATE="$(date +%F)"
LOG="$PROJECT/logs/draft-$DATE.log"
mkdir -p "$PROJECT/logs"

notify() {
  /usr/bin/osascript -e "display notification \"$2\" with title \"업무일지\" sound name \"Ping\"" 2>/dev/null
  echo "$1: $2" >>"$LOG"
}

if ! command -v claude >/dev/null 2>&1; then
  notify ERROR "claude 명령을 찾지 못했습니다"
  exit 1
fi

# 비대화형(claude -p)이라 메모가 없으면 물어볼 상대가 없다. 헛돌지 말고 넘긴다.
if [ ! -f "$PROJECT/notes/$DATE.md" ]; then
  notify SKIP "$DATE 메모가 없어 초안을 건너뜁니다. /daily-log로 직접 작성하세요."
  exit 0
fi

# --yes가 아니라 --draft인 건 의도다. 매일 18:00에 아무도 안 읽은 제출물이 나오면
# "초안 자동 생성 + 사람 확인"이라는 전제가 무너진다. 한 번에 끝내려면 scripts/log.sh를 쓴다.
if claude -p "/daily-log --draft --date $DATE" >>"$LOG" 2>&1; then
  if [ -f "$PROJECT/drafts/$DATE.json" ]; then
    notify OK "$DATE 초안이 준비됐습니다. 확인 후 확정하세요."
  else
    notify WARN "초안 파일이 생성되지 않았습니다. 로그를 확인하세요."
    exit 1
  fi
else
  notify ERROR "초안 생성에 실패했습니다. $LOG 확인"
  exit 1
fi
