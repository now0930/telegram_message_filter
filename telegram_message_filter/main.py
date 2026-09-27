import os
import re
from dotenv import load_dotenv
from telethon import TelegramClient, events
from ollama import AsyncClient

load_dotenv()

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
RAW_CHANNELS = os.getenv('TARGET_CHANNELS', '')
DESTINATION_CHAT_ID = os.getenv('DESTINATION_CHAT_ID')
OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://ollama:11434')

target_channels = []
for ch in RAW_CHANNELS.split(','):
    ch = ch.strip()
    if not ch:
        continue
    if (ch.startswith('-') and ch[1:].isdigit()) or ch.isdigit():
        target_channels.append(int(ch))
    else:
        target_channels.append(ch)

telegram_client = TelegramClient('telegram_session', API_ID, API_HASH)
ollama_client = AsyncClient(host=OLLAMA_HOST)

async def check_if_readable(text):
    prompt = f"""당신은 텔레그램 정보 채널의 수많은 글 중, 사용자가 '진짜 읽을 가치가 있는 글'만 골라내는 AI 편집장입니다.

[판단 기준]
- 합격: 팩트 기반의 뉴스, 시장 분석, 객관적인 지표 발표, 중요한 공지사항.
- 불합격: VIP 멤버십 가입 유도, 레퍼럴/가입 링크, 의미 없는 인사말, 특정 종목 맹목적 매수 추천.

채널 게시글: "{text}"

위 기준에 따라 가장 알맞은 옵션 하나만 단어로 출력하세요.
옵션: [합격, 불합격]"""

    try:
        response = await ollama_client.chat(
            model='hf.co/sky7350/Mica-v0.1-4B:Q5_K_M',
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.0}
        )
        return re.sub(r'[^가-힣]', '', response['message']['content'])
    except Exception as e:
        print(f"Ollama 통신 오류: {e}")
        return "불합격"

@telegram_client.on(events.NewMessage(chats=target_channels))
async def handler(event):
    message_text = event.message.text
    if not message_text:
        return

    chat = await event.get_chat()
    chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', '채널')
    print(f"[{chat_title}] 새 메시지 수신, AI 분석 시작...")

    result = await check_if_readable(message_text)

    if result == "합격":
        print(f"-> 💡 [{chat_title}] 유용한 정보 발견! 포워딩 진행.")
        try:
            dest = int(DESTINATION_CHAT_ID) if DESTINATION_CHAT_ID.lstrip('-').isdigit() else DESTINATION_CHAT_ID
            await telegram_client.send_message(
                dest,
                f"⭐️ [AI 추천 뉴스 - {chat_title}]\n\n{message_text}"
            )
        except Exception as e:
            print(f"텔레그램 메시지 전송 오류: {e}")
    else:
        print(f"-> 🚫 [{chat_title}] 불합격 판정 ({result}). 무시합니다.")

async def main():
    print(f"모니터링 대상 채널 수: {len(target_channels)}개")
    print(f"대상 채널 목록: {target_channels}")
    print("AI 텔레그램 다중 채널 필터 봇이 시작되었습니다...")
    await telegram_client.run_until_disconnected()

if __name__ == '__main__':
    telegram_client.start()
    telegram_client.loop.run_until_complete(main())
