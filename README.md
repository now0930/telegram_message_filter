# AI Telegram 메시지 필터

가입한 Telegram 채널의 새 글을 Ollama로 분류하고, 읽을 가치가 있다고 판정된 글을 지정한 채팅으로 전송하는 Python 서비스입니다. Telegram 봇 토큰 대신 사용자 계정의 API ID와 API Hash로 로그인합니다.

## 현재 지원 범위

독자가 읽을 시간이 부족하다는 전제로 **중요 뉴스만 즉시 전달하고 핵심 요약을 붙입니다.** 원문 전체를 재전송하지 않습니다.

- 태양광·풍력·탄소중립·탄소포집(CCUS/CCS)
- 자동차 자율주행·SDV, 로봇·Physical AI
- AI 반도체·HBM·HBF, AI 에이전트(agent AI/agentic AI)
- 배터리·전고체 배터리, 조선, 방산
- 주요국 환율·정책금리·국채금리·주가·기업 실적과 시장 파급
- 중국·미국·일본·한국을 우선하고, 다른 국가도 관심 산업/주요국 시장에 직접적인 영향이 있으면 포함
- 핵심 사실 최대 3개 + 중요한 이유 + 확인할 점 + Telegram 원문 링크
- 최근 72시간 전달 기록을 이용한 채널 간 동일 본문·같은 사건 중복 제거
- 판단을 바꾸는 새로운 수치, 공식 확인, 계약 확정 등 중요한 후속 사실은 재전달
- SQLite 기록으로 컨테이너 재시작 후에도 중복 제거 유지
- 인증·채널 접근·선별 점수·중복 제외·전송 완료·오류 로그
- 접근 불가능하거나 미가입인 채널은 제외하고 나머지 채널 감시 계속

### 선별 기준

AI가 중요도·깊이·근거를 각각 0~5점으로 평가하고, 실제 전달 여부는 코드가 다음 조건으로 결정합니다.

| 항목 | 기본 통과 기준 |
| --- | --- |
| 분야 | 위 관심 산업 또는 거시경제·주요기업·시장 |
| 중요도 | 3 이상: 관심 분야의 구체적인 변화·소식 |
| 깊이 | 2 이상: 구체적 사실이나 수치가 있는 짧은 기사도 포함 |
| 근거 | 3 이상: 식별 가능한 출처와 구체적 사실 |
| 제외 | 광고·VIP·레퍼럴·수익 보장, 핵심 사실 없는 글 |

기본값은 `MIN_IMPORTANCE=3`입니다. 기존 운영 .env에 4가 있으면 3으로 직접 변경해야 적용됩니다. 4는 기존 심층 기준(깊이 3 이상)을 유지하고, 중요도 5·근거 4 이상의 공식 결정은 깊이 2도 허용합니다. 단순 등락률 나열, 제목·링크만 있는 글, 반복 전망, 관심 단어만 포함한 홍보는 제외합니다. `MIN_IMPORTANCE=5`로 설정하면 최상위 중요 사건만 통과시킵니다.

점수와 설명은 AI 판단입니다. 지원하는 네이버·다음 직접 기사 링크는 모든 채널에서 본문을 읽으며, `@best_article`에 한해 아래 포털 대조를 추가합니다. 분야와 평가 기준은 `telegram_message_filter/news_filter.py`의 `EDITOR_PROMPT`에서 수정합니다.

### 중복 제거

동일 본문은 공백·유니코드 표기를 정규화한 해시로 비교합니다. 표현이나 채널이 다른 보도는 전달된 요약의 핵심 사실과 AI로 비교합니다. 주제가 같아도 실적기간·정책 발표·사건이 다르면 별도 뉴스로 취급합니다. 최근 기록은 15개씩 나누어 전체 비교하므로 전달량이 늘면 처리 지연과 AI 호출량도 늘어납니다.

전송 성공 후에만 기록하며, 동시 수신도 순서대로 처리해 중복 발송을 줄입니다. Telegram 전송 직후 DB 저장 전에 프로세스가 종료되는 경우까지 완전한 1회 발송을 보장하지는 않습니다. 원문 채널의 메시지를 삭제하는 기능은 아닙니다.

### `@best_article` 전용 포털 대조

이 채널은 기존 중요도 기준을 통과한 뒤에도 **네이버·다음 뉴스 검색으로 찾은 기사 본문과 핵심 사실이 일치해야** 전달합니다. API 키나 별도 유료 검색 서비스 없이 공개 뉴스 검색을 이용합니다. 검색에는 게시글에서 추출한 회사/기관·사건 키워드만 보냅니다.

1. 원문을 요약·평가하고 일반 산업/거시 선별 기준을 적용합니다.
2. 네이버·다음에서 검색하고 포털별 최대 3개 기사 본문을 조회합니다.
3. 기본 최근 7일 이내 기사만 사용합니다. 기사 날짜를 읽지 못한 경우 제외합니다.
4. 같은 주체·사건·기간·수치인지 대조합니다. 비슷한 키워드만 있는 기사는 통과 근거가 아닙니다.
5. 선택한 기사 하나가 요약의 핵심 사실 전체를 뒷받침해야 합니다. AI가 제시한 근거 구절도 실제 기사 본문에 존재해야 합니다.
6. 통과하면 기존 중복 제거를 거쳐 요약에 `포털 보도 대조` 기사 링크를 붙입니다. 전달 기록에 근거 링크도 저장합니다.

검색 결과 없음, 본문 조회 차단, 오래된 기사, 근거 부족, 불일치, 검색/AI 오류는 **전달하지 않습니다**. 단일 포털의 조회가 실패해도 다른 포털에서 읽은 일치 기사가 있으면 통과할 수 있습니다. 두 포털 모두의 일치를 요구하는 방식은 아닙니다. 다른 채널은 기존 필터를 사용합니다. `@best_article`은 사용자명과 확인된 채널 ID로 식별합니다.

이 기능은 포털에 실린 보도와의 대조이며 사실의 진실성 보장이나 독립 언론사 두 곳의 교차 검증은 아닙니다. 같은 기사를 여러 언론이 전재할 수도 있고 AI가 대조를 잘못할 수도 있습니다. 속보가 검색에 아직 반영되지 않았거나 기사 본문 구조가 바뀌면 정상 뉴스도 제외될 수 있습니다. 제외된 글의 자동 재검색은 하지 않습니다. 검색·본문 조회는 최대 45초, 검색어 생성부터 기사 대조까지의 전체 추가 검증은 최대 150초로 제한합니다. 그동안 다른 대기 메시지의 처리가 늦어질 수 있습니다.

## 준비

Docker Compose와 Ollama가 필요합니다. Ollama에는 `hf.co/sky7350/Mica-v0.1-4B:Q5_K_M` 모델을 준비하세요. 기본 Compose는 외부 Docker 네트워크 `ollama_network`를 사용합니다. 이 네트워크가 있어야 하며, 필터 컨테이너에서 `OLLAMA_HOST`에 접근할 수 있어야 합니다.

```sh
git clone https://github.com/OWNER/REPOSITORY.git
cd telegram_message_filter/telegram_message_filter
cp .env.example .env
```

### 전체 흐름과 `.env` 구성

모든 기능은 하나의 `telegram-filter` 컨테이너와 하나의 Telegram Userbot 세션을 공유합니다. 입력은 세 갈래입니다. Telegram 채널 글은 뉴스 필터로 들어가고, MacroDroid의 당근 알림은 웹훅으로 들어가며, 채권 모니터는 KIS API에서 직접 가격을 읽습니다. 각 입력은 자체 판정을 거친 뒤 `DESTINATION_CHAT_ID`로만 전송됩니다.

`.env`는 이 흐름을 제어하는 설정 파일입니다. 아래 표에서 각 변수는 한 번만 설명합니다.

| 묶음 | 변수 | 기능과 저장 위치 |
| --- | --- | --- |
| Telegram 연결 | `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TARGET_CHANNELS`, `DESTINATION_CHAT_ID` | 채널을 읽고 세 기능의 통과 알림을 목적지로 전송합니다. 세션은 `telegram_session.session`에 저장하며 Git에 올리지 않습니다. |
| 뉴스 필터 | `OLLAMA_HOST`, `OLLAMA_MODEL`, `MIN_IMPORTANCE`, `DEDUP_HOURS`, `PORTAL_MAX_AGE_DAYS`, `NEWS_DB_PATH` | Ollama가 중요도·근거·깊이를 평가하고 중복을 제거합니다. `@best_article`은 포털 대조를 추가하며 기록은 `news_history.sqlite3`에 저장합니다. |
| 당근 웹훅 | `DEALS_WEBHOOK_TOKEN`, `DEALS_CONFIG_PATH`, `DEALS_DB_PATH`, `DEALS_PORT` | MacroDroid → 웹훅 → `deal_watchlist.json` 가격·지역 판정 → Telegram 전송 순서입니다. 처리 기록은 `deal_notifications.sqlite3`에 저장합니다. 토큰이 비어 있으면 비활성화됩니다. |
| 채권 모니터 | `BOND_MONITOR_ENABLED`, `KIS_APP_KEY`, `KIS_APP_SECRET`, `BOND_WATCHLIST_PATH`, `BOND_DB_PATH`, `BOND_HOUR`, `BOND_MINUTE`, `BOND_INTERVAL_MINUTES` | KIS → 가격·수익률 판정 → Telegram 전송 순서입니다. 목록은 `bond_watchlist.json`, 기록은 `bond_history.sqlite3`에 저장합니다. `BOND_MONITOR_ENABLED=false`이면 이 기능만 꺼집니다. |

감시 계정은 대상 채널에 가입되어 있어야 하며 목적지에 글을 쓸 권한이 있어야 합니다. 개인·봇 계정은 감시 채널로 지원하지 않습니다. 목적지는 감시 채널과 달라야 합니다. `.env`와 `*.session*`은 인증 정보이므로 Git에 올리지 않습니다.

## 최초 로그인과 실행

아래 명령은 `docker-compose.yml`이 있는 디렉터리에서 실행합니다. 최초 로그인에서 전화번호, 인증 코드 및 필요한 경우 2단계 인증 암호를 입력합니다.

```sh
docker compose run --rm telegram-filter sh -c 'pip install -r requirements.txt && python -u main.py --login'
docker compose up -d
docker compose logs -f telegram-filter
```

`필터 준비 완료` 이후 새 게시글을 보내세요. 합격 글은 `전송 완료` 로그의 원본·목적지 메시지 ID로 확인할 수 있습니다. 컨테이너 로그 시각은 호스트의 한국 시각과 다를 수 있습니다.

## 전송 없는 진단

동일한 인증 세션을 사용하는 프로그램을 동시에 실행하지 마세요. 세션 파일을 복사해도 같은 인증을 공유합니다. 로그 확인은 실행 중에도 가능하지만, Telegram에 연결하는 진단은 서비스를 멈춘 뒤 진행합니다.

```sh
docker compose stop telegram-filter
docker compose run --rm telegram-filter sh -c 'pip install -r requirements.txt && python -u main.py --check-latest'
docker compose up -d telegram-filter
```

각 채널의 최신 글 하나의 분야·점수·요약을 출력하고 종료합니다. 이 진단 모드는 포털 대조·중복 판정·전송·전달 기록 저장을 하지 않습니다. 진단 명령이 실패해도 마지막 `up` 명령으로 서비스를 다시 시작하세요.

## 문제 확인

- 준비 완료가 없음: 인증, 채널 접근, 목적지 ID와 시작 오류를 확인합니다.
- 수신 로그가 없음: 시작 이후의 새 글인지, 감시 계정이 가입했는지, 세션을 다른 프로세스에서 사용 중인지 확인합니다.
- 선별 제외: 점수·근거·분야 기준을 통과하지 못한 결과입니다. 로그에 점수와 이유가 나옵니다.
- 포털 대조 제외: 최근 기사 본문을 찾지 못했거나 핵심 사실 일치를 확인하지 못한 결과입니다. 검색 장애는 별도로 기록합니다.
- 중복 제외: 비교 기간 내 이미 전달한 본문 또는 같은 사건입니다.
- 분석/중복 확인 실패: Ollama 연결·모델·응답 형식을 확인합니다. 확인에 실패하면 전송하지 않습니다.
- 전송 실패: 목적지 권한과 Telegram 오류 로그를 확인합니다.

## 검증 및 한계

Python 의존성을 설치한 환경에서 저장소 루트의 회귀 테스트를 실행합니다. 테스트 자체는 외부 연결이나 Telegram 전송을 하지 않습니다.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r telegram_message_filter/requirements.txt
python3 -m unittest discover -s tests -v
python3 -m py_compile telegram_message_filter/*.py
```

회귀 테스트는 점수 기준, 영속 중복 제거, 재작성·후속 사건, 동시 수신, 오류 처리와 원문 링크를 검증합니다. 기존 버전에서 실제 Telegram 전달을 확인했고, 새 편집 기준은 실제 Ollama 모델과 합성 예제로 검증합니다. 장기 무중단 운영 및 다양한 실제 기사에 대한 정확도 평가는 아직 하지 않았습니다.

이 버전은 실행 중 들어오는 새 텍스트 게시글을 처리하는 기본 버전입니다. 과거 글 자동 재처리, 장애 중 누락 복구, 영속 재시도 큐, 수정된 글 재판정, 미디어 전달·OCR은 구현하지 않았습니다. 요약은 길이를 제한하여 전송하며, 20,000자 초과 입력은 분석하지 않습니다. 중복 비교 기간 이전의 뉴스나 AI가 놓친 중복은 다시 전달될 수 있습니다. AI 오류나 전송 실패한 글은 자동 재시도하지 않습니다.

## 기존 설치 업데이트

실행 디렉터리에 `main.py`, `news_filter.py`, `portal_verifier.py`를 모두 복사해야 합니다. `.env`, Telegram 세션, `news_history.sqlite3`는 유지하세요. 저장소를 별도 위치에 내려받았다면 실행 디렉터리에서 다음처럼 적용합니다.

```sh
docker compose stop telegram-filter
# 새 저장소 경로를 실제 경로로 바꾸세요.
cp /path/to/repository/telegram_message_filter/{main.py,news_filter.py,portal_verifier.py,deal_filter.py,deal_bridge.py,requirements.txt,docker-compose.yml,docker-compose.deals.yml} .
# 사용자 품목 설정을 덮어쓰지 않도록 최초 설치에만 복사
if [ ! -f deal_watchlist.json ]; then
  cp /path/to/repository/telegram_message_filter/deal_watchlist.json .
fi
docker compose up -d --force-recreate telegram-filter
docker compose logs -f telegram-filter
```

당근 웹훅을 사용 중이면 위 `up` 명령 대신 `docker compose -f docker-compose.yml -f docker-compose.deals.yml up -d --force-recreate telegram-filter`를 사용하세요.

`.env`의 채널 목록 변경도 `restart`만 하지 말고 `up -d --force-recreate`로 환경 변수를 다시 읽도록 합니다.

### 단일 운영 디렉터리 업데이트

앞으로는 새 `next` 디렉터리를 만들지 않습니다. 임시 디렉터리에 최신 저장소를 clone하고, 검증이 끝나면 기존 운영 디렉터리 `$HOME/telegram_message_filter`의 코드만 교체합니다. 임시 clone은 작업이 끝나면 자동 삭제되며 `.env`, `*.session*`, `*.sqlite3`, 실제 `deal_watchlist.json`은 유지됩니다.

저장소 루트에서 실행하세요.

```sh
SINGLE_RUNTIME_CONFIRM=YES ./scripts/update_single_runtime.sh
```

기존 `clone_restart.sh`도 같은 단일 디렉터리 업데이트 동작을 호출합니다.

```sh
SINGLE_RUNTIME_CONFIRM=YES ./scripts/clone_restart.sh
```

스크립트는 Compose 설정을 먼저 검증하고, 업데이트 실패 시 이전 코드 파일을 복원한 뒤 서비스를 다시 시작합니다. 이미 존재하는 `telegram_message_filter_next*` 또는 `telegram_message_filter_backup*` 디렉터리는 자동 삭제하지 않으므로, 새 운영본이 정상임을 확인한 후 직접 정리하세요.

## 당근 가격 알림 — 안드로이드 알림 연동

공개 웹 검색은 지역 정보는 반환하지만 실매물 목록을 확인할 수 없어 수집기로 사용하지 않습니다. **안드로이드의 당근 키워드 알림을 인증된 웹훅으로 전달**하고, 명시적인 조건을 충족한 알림만 기존 Telegram 연결로 전송합니다. 휴대폰의 MacroDroid 설정이 필요하며, 설정 전에는 매물이 자동 수집되지 않습니다.

관심 품목은 `telegram_message_filter/deal_watchlist.json`에서 편집합니다. 서버는 처리 시 설정을 다시 읽으므로 품목/가격 변경에 재시작은 필요하지 않습니다. 기본 `enabled: false`는 수신·판정만 하는 확인 모드입니다. `true`로 바꾸면 이후 조건을 통과한 새 알림을 Telegram에 전송합니다. 확인 모드에서 이미 처리한 알림은 소급 전송하지 않습니다.

지역·품목·가격은 각 운영자의 `deal_watchlist.json`에서 설정합니다. 공개 문서에는 실제 지역이나 개인별 가격을 기록하지 않습니다. `reference_price`와 `max_price_percent`는 신품 기준가의 일정 비율을 상한으로 사용하고, 품목에 `target_price`를 넣으면 그 금액 이하일 때만 알림을 보냅니다. `target_price`가 있으면 비율 계산보다 우선합니다. 인접 지역은 자동으로 포함하지 않으며, 스피커·노트북처럼 모델이 다양한 품목은 기준가가 실제 동일 모델 시세와 다를 수 있습니다. `name`, `reference_price`, `target_price`, `required_patterns`, `excluded_title_patterns`를 편집해 관심 모델을 구체화할 수 있습니다.

### 판정과 한계

알림 텍스트 자체에서 설정한 지역·판매 중·정확한 가격·모델·미개봉을 확인해야 합니다. 미사용/새상품만 적힌 글, 미개봉급, 개봉 후 미사용, 구매글, 예약금/보증금, 제외 모델/액세서리는 제외합니다. 상태나 가격이 생략된 실제 당근 알림은 `insufficient`로 기록되고 전송되지 않습니다. 알림의 형식은 아직 실제 휴대폰 샘플로 검증하지 않았으므로 연동 후 수신 결과를 확인해야 합니다. 필요한 정보가 원래 알림에 없다면 상세 매물 정보를 추가로 제공하는 방식이 필요합니다.

- 가격은 사용자 지정 기준가입니다. 실시간 중고 거래 시세를 자동 조회하지 않습니다.
- 미개봉과 판매 중 상태는 알림에 적힌 주장이지 실물/현재 상태를 직접 확인한 결과가 아닙니다.
- 알림에 링크가 없으면 당근 앱의 원본 알림에서 확인하도록 안내합니다.
- 동일 알림과 같은 매물 링크·가격은 중복 전송하지 않습니다. 링크 없는 알림의 표현이 달라지면 중복이 생길 수 있습니다.
- 전달 실패는 최대 3회 시도합니다. 24시간 지난 알림은 제외하며 원본 알림은 7일, 전송 중복 기록은 90일 보관합니다.
- Telegram 전송 직후 저장 전에 프로세스가 종료되면 중복 가능성이 있습니다.

### 서버 설정

실행 디렉터리의 `.env`에 무작위 `DEALS_WEBHOOK_TOKEN`을 설정합니다. 비어 있으면 웹훅은 시작하지 않습니다. 토큰은 Git/채팅에 올리지 마세요.

```sh
# 실행 디렉터리에서: 토큰이 없을 때만 생성합니다.
python3 - <<'PYTOKEN'
from pathlib import Path
import secrets
p = Path('.env')
text = p.read_text()
if not any(line.startswith('DEALS_WEBHOOK_TOKEN=') and line.split('=', 1)[1].strip() for line in text.splitlines()):
    lines = [line for line in text.splitlines() if not line.startswith('DEALS_WEBHOOK_TOKEN=')]
    p.write_text('\n'.join(lines) + '\nDEALS_WEBHOOK_TOKEN=' + secrets.token_urlsafe(32) + '\n')
PYTOKEN

docker compose -f docker-compose.yml -f docker-compose.deals.yml up -d --force-recreate telegram-filter
```

`docker-compose.deals.yml`은 현재 서버의 Apache 네트워크 `docker_compose_rest_api_web_network`를 사용합니다. 다른 설치에서는 네트워크 이름을 바꾸세요. 8090 포트는 인터넷에 직접 공개하지 않습니다. HTTPS 가상호스트에 [Apache 예제](deploy/apache-deals.conf)를 추가하고 설정 검사 후 reload합니다.

현재 연결 주소:

- `POST https://your-domain.example/deals/notification`: 알림 수신
- `GET https://your-domain.example/deals/status`: 인증 후 상태 확인
- 공통 헤더: `Authorization: Bearer <DEALS_WEBHOOK_TOKEN 값>`
- 수신 추가 헤더: `X-Notification-App: com.towneers.www`
- 수신 본문 형식: `Content-Type: text/plain; charset=utf-8`

상태에는 `pending`, `preview`, `insufficient`, `rejected`, `sent`, `duplicate`, `failed` 건수와 최근 제외 이유가 표시됩니다. 원본 알림이나 인증 토큰은 상태 응답에 노출하지 않습니다.

### 휴대폰 설정 (MacroDroid)

1. 당근 앱에서 사용할 지역을 설정하고 관심 키워드를 등록합니다. 실제 알림 제공 범위/조건은 앱 설정을 확인하세요.
2. MacroDroid를 설치하고 알림 접근 권한을 허용합니다.
3. 새 매크로의 **알림 수신** 트리거에서 당근(`com.towneers.www`)만 선택하고, 실제 키워드 알림에 맞는 텍스트 필터를 설정합니다. 개인 채팅 알림을 함께 전달하지 마세요.
4. **HTTP Request** 액션에서 위 수신 URL, POST, 헤더 3개를 설정합니다.
5. 본문은 일반 텍스트로 두고 MacroDroid의 **매직 텍스트 선택기**에서 알림 제목·본문·확장 본문을 줄바꿈으로 넣습니다. 지역·가격·판매중 같은 없는 내용을 상수로 덧붙이지 마세요. JSON으로 감싸지 않습니다.
6. 실제 알림 하나를 받은 뒤 상태 API/로그로 수신 결과를 확인합니다. 형식에 필요한 정보가 모두 있으면 `deal_watchlist.json`의 `enabled`를 `true`로 바꾸세요.

MacroDroid 공식 문서: [알림 트리거](https://www.macrodroidforum.com/wiki/index.php/Trigger:_Notification), [HTTP Request](https://www.macrodroidforum.com/wiki/index.php/Action:_HTTP_Request).

### 업데이트 시 주의

뉴스 모듈 외에 `deal_filter.py`, `deal_bridge.py`, `docker-compose.deals.yml`도 복사해야 합니다. 최초 설치에서만 `deal_watchlist.json`을 복사하고, 이후에는 사용자 설정 파일을 보존하세요. 당근 연동을 유지하려면 재생성 시 위 두 Compose 파일을 함께 지정해야 합니다.

## 안전한 Git 푸시

작업 트리가 깨끗하고 원격보다 앞선 커밋만 확인한 뒤 일반 fast-forward 푸시를 하려면 다음 스크립트를 사용합니다. 강제 푸시, 자동 병합, 비밀·런타임 파일이 포함된 커밋은 거부합니다.

```sh
./scripts/safe_push.sh
```

자동화 환경에서는 내용을 별도로 검토한 뒤 `PUSH_CONFIRM=YES ./scripts/safe_push.sh`를 사용하세요. 원격이 앞선 경우에는 스크립트가 중단되므로 먼저 `git pull --rebase` 결과를 확인해야 합니다.

## 국내 회사채 급락 모니터

`telegram_message_filter/bond_monitor.py`는 등록한 **장내 회사채**를 KIS API로 조회합니다. 전체 장외 회사채 시장 스캐너가 아니며, 종목코드·발행사·등급은 운영자가 확인해서 등록합니다. 주문은 실행하지 않습니다.

- 전 거래일 대비 가격 -2% 이하 **또는** 수익률 +50bp 이상이면 감지합니다. 수익률 입력 단위는 %이며 4.5 → 5.0은 +50bp입니다.
- 공식 일별 API에는 수익률 필드가 없어 가격은 일별 API, 수익률은 현재가 API의 `ernn_rate`를 사용합니다. 매일 16시 이후 관측한 수익률을 SQLite에 저장하고, 일별 API가 알려준 직전 거래일 관측치와 비교합니다. 최초 실행·누락일에는 수익률 비교 없이 가격 조건만 적용합니다. 관측 수익률은 공식 일별 확정 종가 수익률과 같다고 보장하지 않습니다.
- 당일 데이터가 없거나 비교하는 두 거래일 중 거래량이 0이면 건너뜁니다. 휴일·거래 부진으로 인한 오래된 가격을 오늘의 급락으로 취급하지 않습니다.
- 네이버 금융 뉴스 검색에서 발행사 이름이 제목에 있는 최근 3일 기사 최대 5개를 수집합니다. 3개 미만이면 확보한 기사만 사용합니다. 검색 차단·HTML 변경·날짜 확인 실패 시 뉴스 없이 감지 결과를 전달합니다.
- Ollama temperature=0.0, 네 가지 분류만 수용합니다. 뉴스 부족·잘못된 출력·AI 장애는 `분류 보류`로 표시합니다. 헤드라인 분류는 원인 확정이 아닙니다.
- 종목/거래일별 성공 발송을 DB에 기록합니다. 실패하면 다음 실행에 재시도합니다. 전송 직후 DB 저장 전에 종료되면 중복 가능성이 있습니다.

### 설정 및 기존 서비스와 동시 실행

`bond_watchlist.json`에는 국채·회사채 감시 목록이 저장됩니다. 이 개인 운영 파일은 Git에서 제외되며 단일 디렉터리 업데이트 때 기존 파일을 보존합니다. 새 서버에서는 `bond_watchlist.example.json`을 복사해 시작한 뒤 실제 목록을 입력합니다. 인증정보와 세션 파일도 Git에 올리지 않습니다.

`.env` 설정:

```ini
BOND_MONITOR_ENABLED=true
KIS_APP_KEY=발급받은_앱키
KIS_APP_SECRET=발급받은_앱시크릿
BOND_WATCHLIST_PATH=bond_watchlist.json
BOND_DB_PATH=bond_history.sqlite3
BOND_HOUR=16
BOND_MINUTE=10
# 선택: 1 이상이면 지정 시각 대신 이 간격(분)으로 반복 조회
BOND_INTERVAL_MINUTES=0
```

`BOND_INTERVAL_MINUTES`가 1 이상이면 지정 시각 대신 해당 분 간격으로 조회합니다(예: `30` 또는 `60`). 거래일·거래량 부족이나 KIS 미지원으로 조회할 수 없는 종목은 SQLite에 날짜별로 기록해 같은 날 반복 조회하지 않고, 다음 날 한 번 다시 확인합니다. 5,000개 이상을 등록할 때는 KIS 호출량과 rate limit을 고려해 30~60분 이상의 간격을 권장합니다.

KIS 실전 Open API 이용 신청이 필요합니다. 키는 서버 `.env`에만 저장합니다. 기존 Telegram 환경 변수와 `OLLAMA_HOST`, `OLLAMA_MODEL`을 재사용합니다. 기본 모델은 `hf.co/sky7350/Mica-v0.1-4B:Q5_K_M`입니다.

```sh
docker compose -f docker-compose.yml -f docker-compose.deals.yml up -d --force-recreate telegram-filter
docker logs -f --tail=100 telegram_filter_bot
```

**기존 서비스의 단일 Telethon 연결에 APScheduler 비동기 작업을 추가하는 방식**입니다. 별도 서비스에서 같은 `telegram_session.session`을 동시에 열거나 세션 파일을 복제해 실행하지 마세요. 기본 월~금 16:10 한국 시각에 실행하며 시작 즉시 실행하지 않습니다. KIS/requests/BeautifulSoup의 동기 작업은 스레드로 분리합니다. APScheduler의 중복 실행은 금지됩니다.

### 발송 없는 테스트와 독립 실행

```sh
# 가상 채권·가상 뉴스 사용. Ollama 분류는 실제 호출, 실패하면 분류 보류.
# Telegram 세션은 열지 않으므로 기존 서비스와 동시에 테스트 가능.
python bond_monitor.py --mock --dry-run
# 실제 KIS 데이터 단회 조회, Telegram 연결/전송 없음
python bond_monitor.py --dry-run
```

독립 실행 시에는 반드시 기존 서비스를 먼저 중지해야 동일한 Userbot 세션을 재사용할 수 있습니다.

```sh
docker compose stop telegram-filter
docker compose run --rm --no-deps telegram-filter sh -c 'pip install -r requirements.txt && python bond_monitor.py --once'
docker compose -f docker-compose.yml -f docker-compose.deals.yml up -d telegram-filter
```

`--once` 없이 실행하면 APScheduler로 계속 감시합니다. 독립 실행 중에는 기존 뉴스 필터를 함께 시작하지 마세요. 두 기능의 상시 운영은 위의 통합 실행을 사용합니다.

데이터 명세: [KIS 공식 일별시세 예제](https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_bond/inquire_daily_itemchartprice), [현재가 예제](https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_bond/inquire_price).

### 필요한 키와 발급 위치

| 설정 | 발급/준비 방법 |
| --- | --- |
| `KIS_APP_KEY`, `KIS_APP_SECRET` | [한국투자증권 KIS Developers](https://apiportal.koreainvestment.com/)에서 실전 Open API 이용 신청 후 발급받는 App Key와 App Secret. 이 모니터가 새로 요구하는 인증 정보입니다. |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | 기존 Userbot 설정 재사용. 신규 설치라면 [Telegram API 개발 도구](https://my.telegram.org/apps)에서 발급합니다. |
| `DESTINATION_CHAT_ID` | 기존 알림 목적지 재사용. API 키가 아닙니다. |
| `OLLAMA_HOST`, `OLLAMA_MODEL` | 기존 로컬 Ollama 설정 재사용. 기본 구성에는 추가 API 키가 없습니다. |

네이버 금융 HTML 수집에는 네이버 검색 API 키를 사용하지 않습니다. KIS 토큰은 App Key/Secret으로 자동 발급하고 메모리에서 만료 전까지 재사용합니다. 계좌번호·주문 권한을 코드 입력으로 요구하지 않으며 실제 인증 정보는 Git에 올리지 않습니다.

배포 순서:

1. 저장소 변경사항을 pull한 뒤 `SINGLE_RUNTIME_CONFIRM=YES ./scripts/update_single_runtime.sh`로 기존 단일 운영 디렉터리를 갱신합니다.
2. 운영 디렉터리에서 `bond_watchlist.example.json`을 `bond_watchlist.json`으로 복사하거나 CSV를 JSON 목록으로 변환해 실제 관심 채권을 입력합니다. `bond_watchlist.json`은 Git에서 제외되며 업데이트 과정에서 보존됩니다.
3. 운영 `.env`에 KIS 키를 넣고 `BOND_MONITOR_ENABLED=true`를 설정합니다.
4. 위 Compose 재생성 명령으로 설정을 적용합니다. 로그의 `회사채 감시 예약 완료`를 확인합니다.

기존 뉴스/당근 기능은 그대로 동작하며 회사채 모니터는 기본 비활성화입니다. 키와 관심 채권 설정을 완료한 뒤 활성화하세요.

검증 현황: 회귀 테스트 63개 통과, 실제 로컬 Mica 연결과 Mock 급락 감지 확인. Mica의 내부 추론이 출력 한도를 소진하는 문제는 `think=False`로 처리하고 JSON enum으로 분류값을 제한했습니다. 반환값은 네 단어 중 하나만 사용합니다. 다만 가상 실적 악화 뉴스가 수급이슈로 분류된 사례가 있어 원인 분류 정확도를 보장하지 않습니다. 실제 KIS 키를 사용한 시세 조회·실제 뉴스 수집·Telegram 발송의 종단 검증은 별도로 필요합니다.


### 게시글 링크 본문과 Ollama 입력 크기

게시글에 네이버 뉴스 또는 다음 뉴스의 직접 기사 URL이 있으면 최대 두 개의
본문을 읽어 원문과 함께 판정합니다. 수집한 기사 URL은 알림에 표시합니다.
기존 발행일·본문 길이 검사를 적용하며, 실패한 링크는 자료에 추가하지 않습니다.
네이버 단축 주소(naver.me)와 Telegram의 숨겨진 텍스트 링크도 지원합니다. 단축 주소는 최대 3회 이동을 확인하며, 지원 기사 주소만 수집합니다. 일반 언론사·다른 단축 서비스·로그인 페이지는 현재 지원하지 않습니다.
합친 입력이 20,000자를 넘으면 일부를 임의로 잘라 판단하지 않고 처리를 중단합니다.

운영 .env의 OLLAMA_NUM_CTX는 기본 16384입니다. Ollama 요청에 num_ctx로 전달해
기존 4096 컨텍스트 초과 오류를 줄입니다. 모델이나 서버가 이 크기를 지원해야 하며,
토큰 초과를 완전히 방지하는 것은 아닙니다. 설정 변경 후 Compose를 재생성하세요.
