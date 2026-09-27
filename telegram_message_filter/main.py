import argparse
import asyncio
import json
import logging
import os
import re
from dotenv import load_dotenv
from telethon import TelegramClient, events, utils
from ollama import AsyncClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

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
ollama_client = AsyncClient(host=OLLAMA_HOST, timeout=90)

def parse_verdict(content):
    try:
        verdict = json.loads(content)["verdict"]
    except (ValueError, KeyError, TypeError):
        # Some models answer in Chinese or wrap the requested word in punctuation.
        verdict = re.sub(r"[^가-힣一-龥]", "", content)
    return {"합격": "합격", "불합격": "불합격", "合格": "합격",
            "不合格": "불합격"}.get(verdict) if isinstance(verdict, str) else None


async def check_if_readable(text):
    prompt = f"""당신은 텔레그램 정보 채널의 수많은 글 중, 사용자가 '진짜 읽을 가치가 있는 글'만 골라내는 AI 편집장입니다.

[판단 기준]
- 합격: 팩트 기반의 뉴스, 시장 분석, 객관적인 지표 발표, 중요한 공지사항.
- 불합격: VIP 멤버십 가입 유도, 레퍼럴/가입 링크, 의미 없는 인사말, 특정 종목 맹목적 매수 추천.

채널 게시글: "{text}"

위 기준에 따라 JSON으로만 출력하세요: {{"verdict": "합격"}} 또는 {{"verdict": "불합격"}}"""

    try:
        response = await ollama_client.chat(
            model='hf.co/sky7350/Mica-v0.1-4B:Q5_K_M',
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.0},
            think=False,
            format={
                'type': 'object',
                'properties': {'verdict': {'type': 'string', 'enum': ['합격', '불합격']}},
                'required': ['verdict'],
                'additionalProperties': False,
            }
        )
        result = parse_verdict(response['message']['content'])
        if result is None:
            logger.error("AI 응답 형식 오류: %r", response['message']['content'])
        return result
    except Exception as e:
        logger.error("Ollama 통신 오류: %s", e)
        return None

async def handler(event):
    message_text = event.message.text
    if not message_text:
        return

    chat = await event.get_chat()
    chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', '채널')
    logger.info("[%s] 새 메시지 수신: id=%s, AI 분석 시작...", chat_title, event.message.id)

    result = await check_if_readable(message_text)

    if result == "합격":
        logger.info(f"-> 💡 [{chat_title}] 유용한 정보 발견! 포워딩 진행.")
        try:
            dest = int(DESTINATION_CHAT_ID) if DESTINATION_CHAT_ID.lstrip('-').isdigit() else DESTINATION_CHAT_ID
            sent = await telegram_client.send_message(
                dest,
                f"⭐️ [AI 추천 뉴스 - {chat_title}]\n\n{message_text}",
                parse_mode=None
            )
            logger.info("[%s] 전송 완료: source_id=%s destination_id=%s",
                        chat_title, event.message.id, sent.id)
        except Exception:
            logger.exception("[%s] 텔레그램 메시지 전송 실패: source_id=%s",
                             chat_title, event.message.id)
    elif result is None:
        logger.error("[%s] AI 판정 실패. 전송하지 않습니다.", chat_title)
    else:
        logger.info(f"-> 🚫 [{chat_title}] 불합격 판정 ({result}). 무시합니다.")

async def main(check_latest=False):
    if not target_channels or not DESTINATION_CHAT_ID:
        raise ValueError("TARGET_CHANNELS와 DESTINATION_CHAT_ID를 설정하세요.")
    logger.info("Telegram 연결 시작...")
    await telegram_client.connect()
    try:
        if not await telegram_client.is_user_authorized():
            raise RuntimeError("Telegram 로그인이 필요합니다. docker compose run --rm telegram-filter python -u main.py --login 을 실행하세요.")
        # Warm the entity cache, including private numeric channel/destination IDs.
        await telegram_client.get_dialogs()
        channels = []
        for configured in target_channels:
            channel = await telegram_client.get_entity(configured)
            if getattr(channel, 'left', False):
                raise RuntimeError(f"감시 계정이 {configured} 채널에 가입되어 있지 않습니다.")
            channels.append(channel)
            logger.info("감시 채널 확인: %s (id=%s)", configured, channel.id)
        dest = int(DESTINATION_CHAT_ID) if DESTINATION_CHAT_ID.lstrip('-').isdigit() else DESTINATION_CHAT_ID
        destination = await telegram_client.get_input_entity(dest)
        if utils.get_peer_id(destination) in {utils.get_peer_id(ch) for ch in channels}:
            raise ValueError("수신 대상은 감시 채널과 달라야 합니다.")
        if check_latest:
            for channel in channels:
                messages = await telegram_client.get_messages(channel, limit=1)
                for message in messages:
                    result = await check_if_readable(message.raw_text) if message.raw_text else None
                    logger.info("진단: channel=%s message=%s date=%s 판정=%s (전송 안 함)",
                                channel.id, message.id, message.date, result)
            return
        telegram_client.add_event_handler(handler, events.NewMessage(chats=channels))
        logger.info("필터 준비 완료. 지금부터 새 메시지를 처리합니다. 이전 글은 --check-latest로 전송 없이 확인할 수 있습니다.")
        await telegram_client.run_until_disconnected()
    finally:
        await telegram_client.disconnect()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-latest', action='store_true', help='채널별 최신 글을 판정만 하고 종료')
    parser.add_argument('--login', action='store_true', help='대화형 Telegram 최초 로그인')
    args = parser.parse_args()
    if args.login:
        telegram_client.start()
        telegram_client.loop.run_until_complete(telegram_client.disconnect())
    else:
        asyncio.run(main(args.check_latest))
