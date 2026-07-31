# 퍼실리테이터 일일 업무일지 자동화

디스코드 채널 로그를 읽어 「코디세이」퍼실리테이터 일일 업무일지(붙임1) HWPX 양식을 채운다.

수집과 문서 생성은 파이썬이, 분류·요약·문체는 Claude가 맡는다. 결정론적인 일을 LLM에 맡기면
재현성이 무너지고, 판단이 필요한 일을 규칙으로 짜면 품질이 무너지기 때문이다.

운영팀이 이 일지를 읽고 반응하므로 **무인 제출이 아니라 초안 자동 생성 + 사람 확인** 구조다.

## 설치

```bash
cp .env.example .env                  # DISCORD_BOT_TOKEN 입력
cp config.example.toml config.toml    # 채널 ID, 이름, 조 입력
chmod +x scripts/draft.sh
```

파이썬 3.11+ 표준 라이브러리만 쓴다. 설치할 패키지가 없다.

### 디스코드 봇 준비

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

## 사용

Claude Code에서:

```
/daily-log                    # 오늘 일지
/daily-log --date 2026-07-30  # 특정 날짜
```

초안을 보여주면 확인·수정하고, 승인하면 `out/일지_<날짜>.hwpx`가 나온다.

### 매일 자동 초안

```bash
sed "s|__PROJECT__|$PWD|g" scripts/com.codysey.dailylog.plist \
  > ~/Library/LaunchAgents/com.codysey.dailylog.plist
launchctl load ~/Library/LaunchAgents/com.codysey.dailylog.plist
```

매일 18:00에 초안까지 만들어 두고 알림을 띄운다. 확인·확정은 `/daily-log`로 한다.

## 구조

```
tools/fetch_discord.py   디스코드 → JSON        (결정론적)
tools/hwpx.py            HWPX 읽기/쓰기 공용
tools/fill_hwpx.py       초안 JSON → HWPX       (결정론적)
tools/verify_hwpx.py     제출 가능 여부 검사
.claude/skills/daily-log 분류·요약·문체         (판단)
style/guide.md           문체 기준 + 누적 규칙
templates/daily.hwpx     원본 양식
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

## 검사

```bash
python3 tests/test_fill_hwpx.py                       # 회귀 테스트
python3 tools/verify_hwpx.py out/일지_<날짜>.hwpx      # 단건 검사
```

안내문구 잔존, 글자색(양식의 파란 안내문 서식을 물려받지 않았는지), 셀 높이 초과,
초안 값 라운드트립을 검사한다. 원본 템플릿을 넣으면 실패해야 정상이다.

## 범위 밖

- 붙임2 **주간** 업무일지 — 출석률·미션 진도율이 디스코드가 아니라 운영팀 시트에서 오는
  별도 데이터라 보류했다. 필요해지면 그 시트를 입력으로 받는 컴포넌트를 따로 만든다.
- 사용자 계정 토큰(셀프봇) — Discord ToS 위반이라 지원하지 않는다.
