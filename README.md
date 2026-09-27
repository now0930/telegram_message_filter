# AI Telegram 메시지 필터

가입한 Telegram 채널의 새 글을 Ollama로 분류하고, 읽을 가치가 있다고 판정된 글을 지정한 채팅으로 전송하는 Python 서비스입니다. Telegram 봇 토큰 대신 사용자 계정의 API ID와 API Hash로 로그인합니다.

## 현재 지원 범위

- 여러 공개·비공개 채널 감시 (`@username` 또는 숫자 ID)
- 직접 작성한 채널 메시지와 텍스트가 있는 게시글 분석
- 합격 글을 채널명과 함께 목적지 채팅으로 전송
- JSON 판정, 한국어·한자 판정값 처리, 90초 AI 요청 타임아웃
- 인증·채널 확인, 수신 메시지 ID, 판정, 전송 완료 및 오류 로그
- 최신 글을 전송 없이 검사하는 진단 모드

합격 기준은 팩트 기반 뉴스, 시장 분석, 객관적 지표 발표, 중요한 공지입니다. VIP 가입 유도, 레퍼럴·가입 링크, 의미 없는 인사, 맹목적 매수 추천은 불합격입니다. AI 분류이므로 사실 검증이나 판정 정확성을 보장하지 않습니다. 기준은 `telegram_message_filter/main.py`의 프롬프트에서 변경할 수 있습니다.

## 준비

Docker Compose와 Ollama가 필요합니다. Ollama에는 `hf.co/sky7350/Mica-v0.1-4B:Q5_K_M` 모델을 준비하세요. 기본 Compose는 외부 Docker 네트워크 `ollama_network`를 사용합니다. 이 네트워크가 있어야 하며, 필터 컨테이너에서 `OLLAMA_HOST`에 접근할 수 있어야 합니다.

```sh
git clone https://github.com/now0930/telegram_message_filter.git
cd telegram_message_filter/telegram_message_filter
cp .env.example .env
```

`.env`에 다음 항목을 설정합니다.

| 설정 | 설명 |
| --- | --- |
| `TELEGRAM_API_ID` | Telegram 사용자 앱 API ID |
| `TELEGRAM_API_HASH` | Telegram 사용자 앱 API Hash |
| `TARGET_CHANNELS` | 쉼표로 구분한 채널 사용자명 또는 ID |
| `DESTINATION_CHAT_ID` | 전송할 채팅 ID 또는 사용자명 |
| `OLLAMA_HOST` | 기본값 `http://ollama:11434` |

감시 계정은 대상 채널에 가입되어 있어야 하며 목적지에 글을 쓸 권한이 있어야 합니다. 목적지는 감시 채널과 달라야 합니다. `.env`와 `*.session*`은 인증 정보이므로 Git에 올리지 않습니다.

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

각 채널의 최신 글 하나를 판정하고 종료합니다. 진단 명령이 실패해도 마지막 `up` 명령으로 서비스를 다시 시작하세요.

## 문제 확인

- 준비 완료가 없음: 인증, 채널 접근, 목적지 ID와 시작 오류를 확인합니다.
- 수신 로그가 없음: 시작 이후의 새 글인지, 감시 계정이 가입했는지, 세션을 다른 프로세스에서 사용 중인지 확인합니다.
- 불합격: 정책에 따라 전송하지 않은 결과입니다. 단순 테스트 문구도 불합격일 수 있습니다.
- AI 판정 실패: Ollama 연결·모델·응답 형식을 확인합니다. 콘텐츠 불합격과 별도로 기록됩니다.
- 전송 실패: 목적지 권한과 Telegram 오류 로그를 확인합니다.

## 검증 및 한계

저장소 루트에서 외부 연결 없이 회귀 테스트를 실행합니다.

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile telegram_message_filter/main.py
```

실제 모델의 뉴스·광고 분류와 테스트 채널에서 목적지까지 합격 글이 전달되는 것을 확인했습니다. 장기 무중단 운영 검증은 아직 하지 않았습니다.

이 버전은 실행 중 들어오는 새 텍스트 게시글을 처리하는 기본 버전입니다. 과거 글 자동 재처리, 장애 중 누락 복구, 영속 재시도 큐, 수정된 글 재판정, 미디어 전달·OCR은 구현하지 않았습니다. Telegram 길이 제한을 넘는 글은 전송 오류가 날 수 있습니다. AI 오류나 전송 실패한 글은 자동 재시도하지 않습니다.
