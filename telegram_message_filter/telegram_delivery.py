"""Send notifications through a bot, retaining Userbot delivery when unconfigured."""
import logging
import os
from types import SimpleNamespace

import httpx

# Bot API URLs contain credentials; never include HTTP request URLs in logs.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


async def send_notification(user_client, destination, text):
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        return await user_client.send_message(
            destination, text, parse_mode=None, link_preview=False)
    chat_id = os.environ['DESTINATION_CHAT_ID']
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': text,
                      'disable_notification': False,
                      'link_preview_options': {'is_disabled': True}})
            data = response.json()
            if response.status_code != 200 or not data.get('ok'):
                raise ValueError('delivery rejected')
            message_id = data['result']['message_id']
    except Exception:
        # Neither credential-bearing URLs nor response bodies may escape to logs.
        raise RuntimeError('Telegram 봇 전송 실패: 토큰·목적지·게시 권한을 확인하세요.') from None
    return SimpleNamespace(id=message_id)
