# CU Viral Monitor

CU에서만 팔거나 CU에서 주목받는 상품 중 **갑자기 검색량·노출이 늘어나는 상품**을 찾기 위한 클라우드 감시 프로젝트입니다.

핵심 원칙은 복잡한 점수화가 아니라 **평소와 다른 급상승 신호가 여러 채널에서 동시에 나타나는지** 확인하는 것입니다.

## 현재 동작

GitHub Actions가 KST 기준 매일 **01:05 / 09:05 / 15:05 / 21:05**에 자동 실행됩니다.

기본 감시 소스:
- Google Trends 한국 급상승 검색어 RSS — 키 불필요
- Google News RSS — 키 불필요

선택 감시 소스:
- NAVER Blog / Cafe 공개 검색 — NAVER API HUB 키 필요
- NAVER DataLab 검색어 트렌드 — NAVER API HUB 키 필요
- YouTube 최근 업로드 검색 — YouTube Data API 키 필요

알림 원칙:
- 한 개 게시물만 뜬 경우는 가급적 무시
- 검색 관심 급상승 + 다른 채널 노출이 겹치거나
- 블로그/카페/YouTube 등 서로 다른 사용자 채널에서 동시에 새 노출이 늘거나
- 품절·재고·구매·후기성 표현이 여러 출처에서 반복될 때 알림
- 매일 오전 9시대에는 이상이 없어도 상태 요약 전송

## Telegram 연결

GitHub 저장소에서 `Settings → Secrets and variables → Actions → New repository secret`으로 아래 값을 추가합니다.

필수:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

권장:
- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`
- `YOUTUBE_API_KEY`

Telegram 키가 없어도 GitHub Actions와 `reports/latest.md`는 동작합니다. 다만 메시지 전송은 하지 않습니다.

## NAVER API HUB

2026년 기준 네이버 검색/검색어 트렌드는 NAVER API HUB 기준으로 연결합니다.

사용 기능:
- Blog Search
- Cafe Article Search
- Search Trend

발급받은 Client ID / Client Secret을 GitHub Secrets의 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`에 넣으면 자동 활성화됩니다.

## YouTube

Google Cloud에서 YouTube Data API v3를 활성화하고 API Key를 발급한 뒤 `YOUTUBE_API_KEY`에 넣습니다.

검색은 최근 업로드만 확인하며 `config.json`의 `youtube_queries`를 사용합니다.

## 수동 테스트

`Actions → CU Viral Monitor → Run workflow`

수동 실행은 `FORCE_TELEGRAM=1`로 처리되므로 Telegram 키가 등록돼 있다면 현재 상태를 즉시 전송합니다.

## 설정 변경

`config.json`에서 검색어를 수정합니다.

주요 항목:
- `search_queries`: Google News / NAVER 검색용
- `youtube_queries`: YouTube 검색용
- `trend_watch_terms`: NAVER DataLab 추적어
- `watch_terms`: 특정 상품명을 직접 추가할 때 사용

예:

```json
"watch_terms": [
  "연세우유 크림빵",
  "두바이 초콜릿"
]
```

## 파일

- `monitor.py` — 감시/판단/Telegram 전송
- `config.json` — 검색어와 감시 조건
- `.github/workflows/viral-monitor.yml` — 클라우드 스케줄
- `data/state.json` — 이미 본 항목 기록
- `reports/latest.md` — 가장 최근 결과

## 목적

이 시스템은 판매량을 예측하거나 자동 발주하지 않습니다.

**“지금 온라인에서 뭔가 평소와 다르게 터지고 있는가?”**를 최대한 빨리 발견해 점주가 발주 여부를 확인하게 하는 조기경보 장치입니다.
