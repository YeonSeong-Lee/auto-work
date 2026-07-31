# 퍼실리테이터 일일 업무일지 자동화

하루치 업무 내용을 읽어 「코디세이」퍼실리테이터 일일 업무일지(붙임1) HWPX 양식을 채운다.

입력원은 세 가지다. 어느 쪽이든 이후 과정은 같다.

| 입력원 | 언제 |
|---|---|
| **직접 입력** (기본) | `/daily-log`가 물어보면 그날 있었던 일을 답한다 |
| **메모 파일** | `notes/<날짜>.md`에 미리 적어두면 그걸 읽는다 |
| **디스코드** | `--discord`. 봇 권한이 잡혀 있을 때 |

문서 생성은 파이썬이, 분류·요약·문체는 Claude가 맡는다. 결정론적인 일을 LLM에 맡기면
재현성이 무너지고, 판단이 필요한 일을 규칙으로 짜면 품질이 무너지기 때문이다.

운영팀이 이 일지를 읽고 반응하므로 **무인 제출이 아니라 초안 자동 생성 + 사람 확인** 구조다.
확인을 마친 파일은 검사를 통과한 뒤 구글 드라이브 제출 폴더까지 자동으로 올라간다.

## 필요한 것

| | 확인 |
|---|---|
| **Claude Code** | `claude --version` — 분류·요약·문체를 맡는다. [설치 안내](https://claude.com/claude-code) |
| **Python 3.11+** | `python3 --version` — 디스코드 수집이 `tomllib`(3.11 표준 편입)을 쓴다. HWPX 생성만 쓴다면 그보다 낮아도 돌지만 3.11에서만 검증했다 |
| **rclone** (선택) | `rclone version` — 드라이브 업로드에만 쓴다. 안 깔면 `out/`까지만 만든다 |

파이썬은 표준 라이브러리만 쓴다. `pip install` 할 게 없다.
디스코드 수집을 안 쓰면 봇 토큰도 필요 없다.

## 시작하기

```bash
git clone <저장소> auto-work && cd auto-work
cp config.example.toml config.toml
chmod +x scripts/*.sh
```

`config.toml`에서 채울 건 두 줄뿐이다. 일지에 고정으로 들어가는 값이니 **본인 이름과 조**를
넣는다.

```toml
author = "홍길동"
team = "1조 (교육생 20명)"
```

`team`은 양식에 그대로 찍히므로 운영팀이 쓰는 표기를 그대로 적으면 된다.
`config.toml`을 안 만들어도 `/daily-log`가 처음 한 번 물어보고 대신 만들어 준다.

마지막으로 이 폴더에서 대화형 `claude`를 한 번 열어 **workspace 신뢰를 승인한다.**
프로젝트 권한 설정(`.claude/settings.json`)이 그때부터 적용된다.

```bash
claude          # 신뢰 여부를 물으면 승인하고 나온다
```

바로 확인해 보려면:

```bash
python3 tests/test_fill_hwpx.py    # 전체 PASS면 준비 끝
```

완성된 일지를 구글 드라이브 제출 폴더까지 자동으로 올리려면 [드라이브 설정](#구글-드라이브-제출)을
한 번 더 해 둔다. 안 해도 `out/`까지는 그대로 돌아간다.

## 사용

프로젝트 폴더에서 Claude Code를 켜고 `/daily-log`를 친다. 그게 전부다.

```
/daily-log                    # 오늘 일지
/daily-log --date 2026-07-30  # 특정 날짜
/daily-log --draft            # 초안까지만 만들고 멈춤
/daily-log --discord          # 디스코드에서 수집
/daily-log --redraft          # 만들어 둔 초안을 버리고 다시 씀
/daily-log --no-upload        # 드라이브에 올리지 않고 out/ 까지만
```

### 한 번 돌리면 이렇게 흘러간다

**① 물어본다** — `notes/<날짜>.md`가 없으면 대화로 묻는다.

```
2026-07-31 (금) 일지를 만듭니다. 오늘 있었던 일을 편하게 적어주세요.
  - 교육생 문의와 어떻게 답했는지
  - 상담·참여 독려한 일
  - 학습 방법이나 미션 진행을 지도한 일
  - 운영팀에 전달할 것 (시설, 이탈 징후, 인수인계)
```

**② 아무렇게나 답한다** — 형식도 문체도 맞출 필요 없다. 다듬는 건 다음 단계 일이다.

```
김OO git push 인증 오류 물어봐서 원격 URL 재설정 알려줌
이OO 3일째 안 나와서 DM 보냄, 내일 온다고 함
미션2 순서 헷갈린다는 사람 3명, 선행 과제부터 하라고 정리해줌
4층 프로젝터 화면 끊김
```

답한 원문은 `notes/2026-07-31.md`에 그대로 저장된다. 나중에 다시 만들거나 분류를 고칠 때
근거가 남고, 대화가 날아가도 복구된다.

**③ 초안을 표로 보여준다** — 세 갈래로 분류하고 `~했습니다` 체로 다듬은 결과다.

```
1차 응대  1건 | [문의 1] git push 시 인증 오류가 발생한다는 문의
               조치 내용: 원격 저장소 URL 재설정 절차를 안내했습니다.
학습 지원  1건 | [참여 독려 1] 3일 연속 미접속한 교육생 1명에게 개별 연락해...
가이드    1건 | [학습 지도 1] 미션2 진행 순서를 묻는 교육생 3명 지도
```

**분류 단위는 메시지가 아니라 사안이다.** 한 주제로 열 번 오갔어도 1건이다.

**④ 고칠 데를 말한다** — "가이드 1건은 문의로 빼줘", "요약 더 짧게" 처럼 말하면 고쳐서 다시
보여준다. 승인할 때까지 반복하고, **확인 없이 최종 파일을 만들지 않는다.**

문장을 고쳤다면 그 교정의 *방향*이 `style/guide.md`의 누적 규칙에 쌓인다. 다음 초안부터
같은 걸 두 번 고치지 않게 된다.

**⑤ 파일이 나온다** — 제출용 파일명은 스크립트가 조립한다.

```
out/[코디세이]0731(금)_홍길동_퍼실리테이터 일일업무일지.hwpx
```

날짜와 이름은 초안에서(즉 `config.toml`에서) 가져오고 요일은 계산한다. 운영팀이 다른 이름
규칙을 쓰면 `tools/fill_hwpx.py`의 `default_out()` 한 함수만 고치면 되고, 한 번만 다르게
내려면 `--out`으로 직접 지정한다.
생성 직후 `verify_hwpx.py`가 검사하며, 통과하지 못한 파일은 넘겨주지 않는다.

**⑥ 드라이브에 올라간다** — 검사를 통과했을 때만.

```
https://drive.google.com/file/d/1a2b3c.../view
```

`config.toml`에 [`[drive]`를 설정](#구글-드라이브-제출)해 두면 여기까지 자동이다. 설정하지
않았으면 이 단계를 조용히 건너뛰고 `out/` 파일로 끝난다.

### 메모를 미리 적어두려면

하루 중에 틈틈이 적어두는 쪽이 편하면, `templates/note.md`를 `notes/<날짜>.md`로 복사해
한 줄에 한 사안씩 적는다.

```markdown
# 2026-07-31

- 김OO git push 인증 오류 → 원격 URL 재설정 안내
- 이OO 3일째 미접속 → DM, 내일 복귀 약속받음
- 미션2 진행 순서 문의 3명 → 선행 과제부터 하도록 순서 정리
- 4층 프로젝터 접촉 불량 → 운영팀 전달 필요
```

파일이 있으면 `/daily-log`가 ①②를 건너뛰고 바로 초안을 보여준다. 자유 서식이지만
**누가 / 무엇을 / 어떻게 했는지**가 있으면 분류가 정확해진다. 모호하면 물어보고 넘어간다.

`notes/`는 교육생 실명이 들어가므로 git에 올라가지 않는다.

### 터미널에서 한 번에 (claude -p)

대화 없이 한 명령으로 제출용 파일까지 끝낸다. 입력은 셋 중 아무거나 된다.

```bash
scripts/log.sh "김OO git 오류 답변, 이OO 미접속 DM, 미션2 순서 3명 정리"   # 인자
echo "..." | scripts/log.sh                                            # stdin
pbpaste    | scripts/log.sh                                            # 클립보드 (macOS)
scripts/log.sh --date 2026-07-30                                       # notes/ 파일
```

마지막 줄에 생성된 경로만 남으므로 그대로 이어 쓸 수 있다.

```bash
open "$(scripts/log.sh)"        # macOS. 리눅스면 xdg-open
```

드라이브 링크는 표준출력을 더럽히지 않게 **stderr로** 따로 나온다. 화면에는 보이지만
`$(...)`에는 안 잡힌다. `[drive]`를 설정해 뒀는데 업로드가 안 됐으면 래퍼가 종료 코드 2로
끝나니, 파일만 나오고 제출이 빠진 걸 모르고 지나갈 일은 없다.

확인 단계를 건너뛰게 하는 건 `--yes` 플래그다. 래퍼가 이걸 붙여 준다.

**`--yes`는 확인을 건너뛰지 검사를 건너뛰지 않는다.** `verify_hwpx.py`는 그대로 돌고,
통과하지 못하면 파일을 내주지 않는다. 입력이 아예 없으면 하루를 지어내지 않고 멈춘다.

> 대신 **문체와 분류를 아무도 검토하지 않는다.** 이 시스템에서 유일한 치명 오류가 문체라
> `--yes`로 만든 파일은 한 번 열어보고 내는 편이 안전하다. 고칠 게 있으면 `/daily-log`를
> 대화형으로 다시 돌리면 되고, 그때 한 교정이 `style/guide.md`에 규칙으로 쌓인다.

#### 권한 — 래퍼를 쓰는 이유

비대화형은 권한 질문에 답할 수 없다. `.claude/settings.json`에 필요한 명령을 허용해 뒀지만
**프로젝트 설정은 workspace를 신뢰해야 적용되고, 신뢰 다이얼로그는 `-p`에서 뜨지 않는다.**
그래서 `scripts/log.sh`가 같은 목록을 `--allowedTools`로 직접 넘긴다 — 별도 준비 없이 바로 돈다.

`claude -p`를 맨손으로 부르고 싶으면 대화형 `claude`를 이 폴더에서 한 번 열어 신뢰를
승인해 두면 된다. 그 뒤로는 아래가 그대로 동작한다.

```bash
echo "..." | claude -p "/daily-log --yes"
claude -p "/daily-log --yes --date 2026-07-30"
```

승인 전에는 `Ignoring N permissions.allow entries ... this workspace has not been trusted`가
뜨면서 쓰기가 막힌다.

허용 목록을 손볼 일이 있으면 **파일 쓰기는 `Edit(경로)`로 적는다.** 파일 권한 검사는 `Edit`
규칙만 보고 그게 Write를 포함한 모든 편집 도구를 덮는다. `Write(경로)`로 적으면 조용히
무시된다 (`Write(notes/**) is not matched by file permission checks` 경고가 뜬다).

### 매일 자동 초안 (macOS)

```bash
sed "s|__PROJECT__|$PWD|g" scripts/com.codysey.dailylog.plist \
  > ~/Library/LaunchAgents/com.codysey.dailylog.plist
launchctl load ~/Library/LaunchAgents/com.codysey.dailylog.plist
```

매일 18:00에 초안까지 만들어 두고 알림을 띄운다. 확인·확정은 `/daily-log`로 한다.
리눅스면 cron에 `0 18 * * * /경로/scripts/draft.sh`를 넣으면 된다 (알림은 osascript라
안 뜨고 `logs/`에만 남는다).

**만들어 둔 초안은 다시 쓰지 않는다.** `/daily-log`로 확정할 때 `drafts/<날짜>.json`이 있으면
그걸 이어받아 확인 단계부터 시작하므로, 그 사이에 파일을 직접 고쳐 뒀어도 그대로 살아 있다.
초안을 버리고 처음부터 다시 쓰려면 `--redraft`를 준다.

**`notes/<날짜>.md`가 있을 때만 동작한다.** 비대화형으로 도는 자리라 물어볼 상대가 없기
때문이다. 메모가 없으면 건너뛰었다고 알림만 뜬다.

## 구글 드라이브 제출

검사를 통과한 파일을 운영팀 폴더에 자동으로 올린다. 전송은 rclone에 맡긴다 — OAuth 토큰
갱신을 직접 다루지 않으려는 이유이고, 덕분에 launchd나 `claude -p` 같은 비대화형에서도 돈다.

**한 번만 설정하면 된다.**

```bash
brew install rclone
rclone config
```

`rclone config`가 묻는 것만 답한다. 나머지는 엔터로 넘긴다.

| 질문 | 답 |
|---|---|
| `n/s/q` | `n` (새 리모트) |
| `name` | `gdrive` |
| `Storage` | `drive` (구글 드라이브) |
| `client_id` / `client_secret` | 빈칸 |
| `scope` | `1` (full access) — 기존 폴더에 올려야 하므로 `drive.file`로는 부족하다 |
| `Edit advanced config` | `n` |
| `Use web browser to authenticate` | `y` → 브라우저에서 계정 승인 |

그다음 `config.toml`에 제출 폴더를 적는다. **드라이브에서 폴더를 열고 주소창을 그대로
붙여넣으면 된다.**

```toml
[drive]
remote = "gdrive"
folder = "https://drive.google.com/drive/folders/1NRN0NvjEWKVw2Dv8j2eT1PSuwDNXT8H1"
```

폴더가 바뀌면 이 한 줄만 고친다. 주소는 코드 어디에도 박혀 있지 않다.
폴더 ID만 적어도 되고, 한 번만 다른 곳에 올리려면 `/daily-log --folder <URL>`을 쓴다.

올리기 전에 어디로 가는지 확인해 볼 수 있다.

```bash
python3 tools/upload_drive.py "out/<파일명>.hwpx" --dry-run   # 대상만 확인
python3 tools/upload_drive.py "out/<파일명>.hwpx"             # 실제 업로드
```

**같은 이름이 이미 있으면 그 파일을 갱신한다.** 초안을 고쳐 다시 올려도 폴더에는 하루치
파일이 하나만 남고 공유 링크도 그대로다.

`[drive]`를 안 적으면 업로드를 건너뛰고 `out/`까지만 만든다. rclone 없이 쓰던 방식 그대로다.

### 전용 client_id (권장)

위 절차대로 `client_id`를 비워 두면 rclone 공용 client_id를 쓰는데, 실행할 때마다 이 경고가
나온다.

```
This remote uses rclone's shared Google Drive client_id, which is being retired
and will stop working during 2026.
```

**2026년 중 동작을 멈춘다고 예고된 상태다.** 지금은 쓸 수 있지만 어느 날 업로드가 통째로
깨질 수 있으니, 계속 쓸 거라면 전용 client_id를 만들어 두는 편이 안전하다.
[rclone 안내](https://rclone.org/drive/#making-your-own-client-id)대로 Google Cloud 콘솔에서
OAuth 클라이언트(데스크톱 앱)를 만든 뒤 다시 설정하면 된다.

```bash
rclone config update gdrive client_id <발급받은_ID> client_secret <발급받은_시크릿>
rclone config reconnect gdrive:      # 새 client_id로 다시 인증
```

### 디스코드에서 수집하려면 (선택)

```bash
cp .env.example .env                  # DISCORD_BOT_TOKEN 입력
```

`config.toml`의 주석 처리된 `[[channels]]`와 `[work_hours]`도 풀어 채운다.

1. [Developer Portal](https://discord.com/developers/applications)에서 앱 생성 → Bot 추가
2. **Bot 화면에서 `MESSAGE CONTENT INTENT`를 켠다** — 이게 없으면 본문을 못 읽는다
3. OAuth2 URL Generator에서 `bot` 스코프 + `Read Messages/View Channels`,
   `Read Message History` 권한으로 초대 링크를 만들어 서버에 초대한다
4. 서버 관리자가 아니면 이 단계에 협조가 필요하다

권한이 제대로 잡혔는지 먼저 확인한다:

```bash
python3 tools/fetch_discord.py --date 2026-07-30 --dry-run
```

채널별 건수가 나오면 정상이다. 0건이면 intent나 채널 권한을 의심한다.

## 구조

```
notes/<날짜>.md          하루치 메모 (직접 작성, git 제외)
templates/note.md        메모 예시
scripts/log.sh           터미널에서 한 번에 (claude -p 래퍼)
scripts/draft.sh         매일 18:00 초안 (launchd)
.claude/settings.json    헤드리스 실행에 필요한 권한 허용
tools/fetch_discord.py   디스코드 → JSON        (결정론적, 선택)
tools/hwpx.py            HWPX 읽기/쓰기 공용
tools/fill_hwpx.py       초안 JSON → HWPX       (결정론적)
tools/verify_hwpx.py     제출 가능 여부 검사
tools/upload_drive.py    드라이브 업로드         (결정론적, 선택)
.claude/skills/daily-log 분류·요약·문체         (판단)
style/guide.md           문체 기준 + 누적 규칙
templates/daily.hwpx     원본 양식 (빈 양식)
templates/daily.signed.hwpx  서명 박은 양식 (git 무시, 있으면 이걸 쓴다)
```

`style/guide.md`가 품질의 중심이다. 유일한 치명 오류가 문체이므로, 초안을 고칠 때마다
그 교정 방향이 규칙으로 쌓이고 다음 초안의 수정량이 줄어든다.

## 분량 제한

양식은 셀 높이가 고정이라 내용이 넘치면 표가 아래로 밀린다. 한 줄은 한글 49자다.

| 항목 | 최대 |
|---|---|
| 오늘 업무 요약 | **1줄** |
| 문의 / 상담 / 학습지도 상세 | 각 7줄 |
| 운영팀 전달사항 | 9줄 |

넘치면 검사에서 걸리고 몇 줄을 줄여야 하는지 알려준다. 그대로 내보내려면
`--allow-overflow`를 주면 경고만 하고 통과시킨다.

## 서명

작성자 칸의 손글씨 서명은 양식에 그림(`BinData/image1.png`)으로 박아 둔다. `(`와 `인)`
사이에 글자처럼 끼워져 있어서, 이름을 채워 넣어도 `홍길동 (서명인)` 모양으로 그대로 남는다.
산출물마다 따로 도장을 찍을 필요가 없다.

손글씨 서명은 개인 정보라 저장소에 올리지 않는다. 그래서 양식이 둘이다.

| 파일 | git | 내용 |
|---|---|---|
| `templates/daily.hwpx` | 추적함 | 빈 양식. 서명 없음 |
| `templates/daily.signed.hwpx` | **무시함** | 내 서명이 박힌 양식 |

`fill_hwpx.py`는 서명본이 있으면 그걸, 없으면 빈 양식을 쓴다. 그래서 클론 직후에도 바로
돌아가고, 서명본을 만들어 두면 그때부터 자동으로 서명이 찍힌다. `--template`으로 직접
지정할 수도 있다.

서명본은 `templates/daily.hwpx`를 한글에서 열어 작성자 칸의 `(`와 `인)` 사이에 서명 그림을
넣고 `templates/daily.signed.hwpx`로 저장하면 된다. 그림은 **글자처럼 취급**으로 넣어야
칸이 밀리지 않는다. 스크립트는 양식에 있는 그림을 그대로 옮길 뿐 새로 만들지 않는다.

서명이 조용히 지워지는 일이 없도록 회귀 테스트(`서명_유지`)가 지킨다. 빈 양식으로 돌리면
검사할 것이 없으므로 `SKIP`으로 넘어간다.

## 검사

```bash
python3 tests/test_fill_hwpx.py                       # 회귀 테스트
python3 tests/test_upload_drive.py                    # 업로드 회귀 테스트
python3 tools/verify_hwpx.py "out/<파일명>.hwpx"        # 단건 검사
```

업로드 테스트는 PATH에 가짜 rclone을 심어 돌린다. 네트워크도 드라이브 계정도 쓰지 않는다.

안내문구 잔존, 글자색(양식의 파란 안내문 서식을 물려받지 않았는지), 셀 높이 초과,
초안 값 라운드트립을 검사한다. 원본 템플릿을 넣으면 실패해야 정상이다.

## 막힐 때

| 증상 | 원인과 해결 |
|---|---|
| `설정 파일이 없습니다: config.toml` | `--discord`를 쓸 때 뜬다. `cp config.example.toml config.toml` 후 채운다 |
| `No module named 'tomllib'` | 파이썬이 3.11 미만이다. 디스코드 수집에서만 난다 |
| 이름·조가 매번 다시 물어봐짐 | `config.toml`이 없다. 한 번 만들어 두면 안 묻는다 |
| `Ignoring N permissions.allow entries ... not been trusted` | 이 폴더에서 `claude`를 한 번 열어 workspace 신뢰를 승인한다 |
| `claude 명령을 찾지 못했습니다` | Claude Code 미설치이거나 PATH에 없다. `scripts/*.sh`는 `~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`을 본다 |
| `permission denied: scripts/log.sh` | `chmod +x scripts/*.sh` |
| `N줄이 필요한데 7줄만 들어갑니다` | 내용이 셀 높이를 넘었다. 항목을 지우지 말고 `(유사 문의 3건)`처럼 묶는다 |
| 초안이 안 만들어지고 멈춤 | 입력이 없어서다. 지어내지 않고 멈추는 게 정상. stdin·인자·`notes/<날짜>.md` 중 하나를 준다 |
| 디스코드 0건 | `MESSAGE CONTENT INTENT`가 꺼졌거나 채널 권한이 없다. `--dry-run`으로 확인 |
| 고친 초안이 원래대로 돌아감 | 없어야 정상이다. `drafts/<날짜>.json`이 있으면 다시 만들지 않는다. 일부러 새로 쓰려면 `--redraft` |
| `업로드 건너뜀 ([drive] 미설정)` | 실패가 아니다. [`[drive]`를 설정](#구글-드라이브-제출)하면 올라간다 |
| `rclone이 설치되어 있지 않습니다` | `brew install rclone && rclone config`. 안 쓸 거면 `config.toml`에서 `[drive]`를 지운다 |
| `rclone 리모트 'gdrive'가 없습니다` | `rclone config`로 만들지 않았거나 이름이 다르다. `[drive].remote`를 실제 이름에 맞춘다 |
| `드라이브 폴더를 알아볼 수 없습니다` | `[drive].folder`에 폴더 주소나 ID가 아닌 값이 들어갔다. 드라이브에서 폴더를 열고 주소창을 그대로 붙여넣는다 |
| 업로드가 403/404로 실패 | 그 계정에 폴더 쓰기 권한이 없거나 폴더 ID가 틀렸다. `--dry-run`으로 대상부터 확인 |
| `shared Google Drive client_id ... being retired` | 경고일 뿐 아직 동작한다. 2026년 중 멈추므로 [전용 client_id](#전용-client_id-권장)를 만들어 두는 편이 안전하다 |

`out/`, `drafts/`, `notes/`, `logs/`는 모두 git에 올라가지 않는다. 교육생 실명이 들어가기
때문이다. 지워도 언제든 다시 만들 수 있다.

## 다른 과정에 쓰려면

이 저장소는 「코디세이」붙임1 양식에 맞춰져 있다. 다른 서식으로 옮기려면 두 군데를 본다.

- `templates/daily.hwpx` — 양식 파일을 교체한다
- `tools/fill_hwpx.py`의 `CELL` — 표의 행·열 좌표 맵. 양식이 바뀌면 여기만 고치면 된다
  (`tools/hwpx.py`는 표를 인덱스가 아니라 "일일 업무일지"라는 내용으로 찾으므로,
  제목이 다르면 `find_daily_table`도 함께 본다)

분류 기준·문체·분량 제한은 `.claude/skills/daily-log/SKILL.md`와 `style/guide.md`에 있다.
파이썬을 건드릴 일은 거의 없다.

## 범위 밖

- 붙임2 **주간** 업무일지 — 출석률·미션 진도율이 디스코드가 아니라 운영팀 시트에서 오는
  별도 데이터라 보류했다. 필요해지면 그 시트를 입력으로 받는 컴포넌트를 따로 만든다.
- 사용자 계정 토큰(셀프봇) — Discord ToS 위반이라 지원하지 않는다.
