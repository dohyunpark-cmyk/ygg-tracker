# YGG Competitor Tracker

YGG(Yanolja Group)의 B2B Bed bank 경쟁사 — Web Travel Group(WebBeds), TBO Tek, HBX Group — 의 주가·뉴스를 매일 09:00 KST에 자동 갱신하는 정적 대시보드입니다.

## 아키텍처

```
[ GitHub Actions, 매일 00:00 UTC (= 09:00 KST) ]
        │
        ▼
  fetch_data.py
   ├── yfinance            : 종가, 52w 범위, 시총, 3개월 sparkline
   └── Finnhub / Yahoo News : 최근 60일 헤드라인 + 감성분류
        │
        ▼
   data.json (commit & push)
        │
        ▼
[ GitHub Pages, 정적 호스팅 ]
        │
        ▼
   index.html  ← fetch('./data.json')
```

브라우저에서 별도 API 키 없이 바로 동작하며, 갱신은 백그라운드(Actions)에서만 일어납니다.

## 셋업 (5분 소요)

### 1. GitHub 리포지토리 생성

이 폴더 그대로 GitHub에 push:

```bash
git init
git add .
git commit -m "init: ygg competitor tracker"
git branch -M main
git remote add origin git@github.com:<OWNER>/ygg-tracker.git
git push -u origin main
```

### 2. Finnhub 키 (선택)

뉴스 품질을 더 높이려면 [finnhub.io](https://finnhub.io/) 무료 계정에서 API 키 발급 후:

- 리포지토리 → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `FINNHUB_API_KEY`, Value: 발급받은 키

키가 없어도 Yahoo Finance 뉴스로 자동 폴백되므로 동작에는 지장 없음.

### 3. GitHub Pages 활성화

- 리포지토리 → **Settings → Pages**
- Source: **Deploy from a branch**
- Branch: `main` / `/ (root)` → Save

URL: `https://<OWNER>.github.io/ygg-tracker/`

### 4. 첫 데이터 갱신

GitHub Actions가 즉시 실행되도록 트리거:

- 리포지토리 → **Actions → Update YGG dashboard data → Run workflow**

워크플로우가 약 1~2분 후 완료되면 `data.json`이 자동 커밋되고, GitHub Pages가 재배포되어 정상 표시됩니다.

## 로컬 테스트

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. (선택) Finnhub 키 export
export FINNHUB_API_KEY=your_key_here

# 3. 데이터 가져오기
python fetch_data.py

# 4. 정적 서버로 index.html 띄우기 (CORS 회피)
python -m http.server 8000
```

브라우저에서 http://localhost:8000 접속.

## 종목 추가/변경

`fetch_data.py`의 `STOCKS` 리스트만 수정하면 됩니다:

```python
{
    "id": "TUI",                    # 카드 식별자 (3~4자)
    "ticker": "ETR:TUI1",           # 표시용 티커
    "yahoo": "TUI1.DE",             # yfinance 심볼
    "finnhub": "TUI1.DE",           # Finnhub 심볼 (대부분 yahoo와 동일)
    "name": "TUI AG",
    "subtitle": "독일 패키지 투어 운영사",
    "currency": "EUR",
    "symbol": "€",
}
```

추가 후 `index.html`의 카드 영역에도 동일한 `id`로 카드 한 개 더 추가하면 끝. CSS 변수 `--accent-XXX`도 색상 추가 권장.

## 갱신 주기 변경

`.github/workflows/update.yml`의 cron 표현식 수정:

```yaml
- cron: "0 0 * * *"   # 매일 09:00 KST
- cron: "0 */6 * * *" # 6시간마다
- cron: "0 22 * * 1-5" # 평일 오전 7시 KST (전일 미주 종가 반영)
```

## 트러블슈팅

| 증상 | 원인·조치 |
|---|---|
| 카드가 비어있고 "데이터가 비어있습니다" 배너 | Actions를 한 번도 안 돌렸거나 실패. `Actions` 탭 로그 확인 후 수동 실행. |
| `Last updated`가 며칠 전 | Actions cron이 비활성화되었을 가능성. 60일 이상 push가 없으면 GitHub가 스케줄을 끔 → 아무 커밋이나 한 번 push. |
| 특정 종목만 가격이 `—` | yfinance가 일시적으로 해당 심볼 거부. 로그 확인 후 재실행. |
| 뉴스가 영어/스페인어로 섞여 나옴 | yfinance.news는 Yahoo의 원본 헤드라인을 그대로 가져옴 — 다국어 지원 시 별도 번역 단계 추가 필요. |
| 로컬에서 `data.json` fetch 실패 (CORS) | `file://` 프로토콜에서는 fetch 불가. 반드시 `python -m http.server`로 띄울 것. |

## 비용

전부 무료 tier로 충분:
- GitHub Actions: public repo는 무제한 (private은 월 2,000분 무료, 이 워크플로우는 회당 ~1분)
- GitHub Pages: 무료 (월 100GB bandwidth)
- yfinance: 무료, 키 불필요
- Finnhub: 무료 60 req/min — 3 종목이라 분당 호출 3회 수준

## 라이선스

내부용. yfinance·Finnhub의 데이터 사용 약관 준수 필요. 매매 의사결정의 직접 근거로 활용 금지.
