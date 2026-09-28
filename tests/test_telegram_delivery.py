import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from telegram_delivery import send_notification

class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_requests_audible_notification_and_returns_id(self):
        response = SimpleNamespace(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 12}})
        client = AsyncMock()
        client.post.return_value = response
        with patch.dict(os.environ, TELEGRAM_BOT_TOKEN='test', DESTINATION_CHAT_ID='-100123'), patch('telegram_delivery.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = client
            user = AsyncMock()
            result = await send_notification(user, 'ignored', 'hello')
            self.assertEqual(result.id, 12)
            self.assertFalse(client.post.call_args.kwargs['json']['disable_notification'])
            user.send_message.assert_not_awaited()

    async def test_failed_bot_does_not_fallback_or_leak_token(self):
        client = AsyncMock()
        client.post.side_effect = ValueError('secret URL')
        with patch.dict(os.environ, TELEGRAM_BOT_TOKEN='secret', DESTINATION_CHAT_ID='-100123'), patch('telegram_delivery.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = client
            user = AsyncMock()
            with self.assertRaises(RuntimeError) as error:
                await send_notification(user, 'ignored', 'hello')
            self.assertNotIn('secret', str(error.exception))
            user.send_message.assert_not_awaited()
