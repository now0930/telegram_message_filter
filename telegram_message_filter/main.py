import argparse
import asyncio
import logging
import os
from dotenv import load_dotenv
from telethon import TelegramClient, events, utils
from ollama import AsyncClient
from news_filter import History, NewsFilter
from portal_verifier import PortalVerifier

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

news_filter = None


async def handler(event):
    text = event.message.text or ''
    # TextUrl entities carry addresses that are absent from visible message text.
    for entity in getattr(event.message, 'entities', None) or []:
        url = getattr(entity, 'url', None)
        if isinstance(url, str) and url.startswith(('https://', 'http://')) and url not in text:
            text += '\n' + url
    if not text:
        return
    logger.info("새 메시지 수신: chat=%s id=%s", event.chat_id, event.message.id)
    try:
        chat = await event.get_chat()
        username = getattr(chat, 'username', None)
        if username:
            source = f"https://t.me/{username}/{event.message.id}"
        elif event.is_channel:
            source = f"https://t.me/c/{chat.id}/{event.message.id}"
        else:
            source = f"{getattr(chat, 'title', '채팅')} / 메시지 {event.message.id}"
        dest = int(DESTINATION_CHAT_ID) if DESTINATION_CHAT_ID.lstrip('-').isdigit() else DESTINATION_CHAT_ID

        async def send(brief):
            from telegram_delivery import send_notification
            return await send_notification(telegram_client, dest, brief)

        outcome = await news_filter.process(text, source, send,
                                            channel_username=username, channel_id=chat.id)
        logger.info("chat=%s source_id=%s %s", event.chat_id, event.message.id, outcome)
    except Exception:
        logger.exception("분석/중복 확인/전송 실패: chat=%s source_id=%s", event.chat_id, event.message.id)


async def main(check_latest=False):
    global news_filter
    if not target_channels or not DESTINATION_CHAT_ID:
        raise ValueError("TARGET_CHANNELS와 DESTINATION_CHAT_ID를 설정하세요.")
    history = History(os.getenv('NEWS_DB_PATH', 'news_history.sqlite3'),
                      hours=int(os.getenv('DEDUP_HOURS', '72')))
    news_filter = NewsFilter(ollama_client,
                            os.getenv('OLLAMA_MODEL', 'hf.co/sky7350/Mica-v0.1-4B:Q5_K_M'),
                            history, int(os.getenv('MIN_IMPORTANCE', '3')),
                            portal_verifier=PortalVerifier(
                                max_age_days=int(os.getenv('PORTAL_MAX_AGE_DAYS', '7'))))
    deal_bridge = None
    bond_monitor = None
    bond_scheduler = None
    logger.info("@best_article 추가 필터: 네이버·다음 기사 본문 대조 필수 (API 키 불필요)")
    logger.info("Telegram 연결 시작...")
    try:
        await telegram_client.connect()
        if not await telegram_client.is_user_authorized():
            raise RuntimeError("Telegram 로그인이 필요합니다. docker compose run --rm telegram-filter python -u main.py --login 을 실행하세요.")
        # Warm the entity cache, including private numeric channel/destination IDs.
        await telegram_client.get_dialogs()
        channels = []
        for configured in target_channels:
            try:
                channel = await telegram_client.get_entity(configured)
                if getattr(channel, 'left', False):
                    raise RuntimeError("감시 계정이 채널에 가입되어 있지 않습니다.")
                if not getattr(channel, 'broadcast', False) and not getattr(channel, 'megagroup', False):
                    raise ValueError("채널/슈퍼그룹이 아닙니다. 봇·개인 계정은 감시하지 않습니다.")
                channels.append(channel)
                logger.info("감시 채널 확인: %s (id=%s)", configured, channel.id)
            except Exception:
                logger.exception("감시 제외: %s (주소와 가입 상태를 확인하세요)", configured)
        if not channels:
            raise RuntimeError("접근 가능한 감시 채널이 없습니다.")
        logger.info("감시 활성화: 설정 %s개 중 %s개", len(target_channels), len(channels))
        dest = int(DESTINATION_CHAT_ID) if DESTINATION_CHAT_ID.lstrip('-').isdigit() else DESTINATION_CHAT_ID
        destination = await telegram_client.get_input_entity(dest)
        if utils.get_peer_id(destination) in {utils.get_peer_id(ch) for ch in channels}:
            raise ValueError("수신 대상은 감시 채널과 달라야 합니다.")
        if check_latest:
            for channel in channels:
                messages = await telegram_client.get_messages(channel, limit=1)
                for message in messages:
                    result = await news_filter.analyze(message.raw_text) if message.raw_text else None
                    logger.info("진단: channel=%s message=%s date=%s 판정=%s (전송 안 함)",
                                channel.id, message.id, message.date, result)
            return
        if os.getenv('DEALS_WEBHOOK_TOKEN'):
            from deal_bridge import DealBridge

            async def send_deal(message):
                from telegram_delivery import send_notification
                return await send_notification(telegram_client, destination, message)

            deal_bridge = DealBridge(os.getenv('DEALS_CONFIG_PATH', 'deal_watchlist.json'),
                                     os.getenv('DEALS_DB_PATH', 'deal_notifications.sqlite3'),
                                     os.environ['DEALS_WEBHOOK_TOKEN'], send_deal)
            await deal_bridge.start(port=int(os.getenv('DEALS_PORT', '8090')))
        if os.getenv('BOND_MONITOR_ENABLED', 'false').lower() == 'true':
            from bond_monitor import BondMonitor

            async def send_bond(message):
                from telegram_delivery import send_notification
                return await send_notification(telegram_client, destination, message)

            bond_monitor = BondMonitor(send_bond)
            bond_scheduler = bond_monitor.start()
            logger.info('회사채 감시 예약 완료 (Asia/Seoul, 기존 Telethon 연결 공유)')
        telegram_client.add_event_handler(handler, events.NewMessage(chats=channels))
        logger.info("필터 준비 완료. 지금부터 새 메시지를 처리합니다. 이전 글은 --check-latest로 전송 없이 확인할 수 있습니다.")
        await telegram_client.run_until_disconnected()
    finally:
        if bond_scheduler:
            bond_scheduler.shutdown(wait=False)
        if bond_monitor:
            async with bond_monitor.lock:
                bond_monitor.db.close()
        if deal_bridge:
            await deal_bridge.close()
        await telegram_client.disconnect()
        history.close()


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
