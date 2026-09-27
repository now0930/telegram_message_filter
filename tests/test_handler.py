import ast
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

source = Path(__file__).parents[1] / 'telegram_message_filter' / 'main.py'
module = ast.parse(source.read_text())
handler = next(n for n in module.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'handler')

class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setup_handler(self, verdict):
        client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=42)))
        classify = AsyncMock(return_value=verdict)
        namespace = dict(telegram_client=client, check_if_readable=classify,
                         DESTINATION_CHAT_ID='-123', logger=logging.getLogger('test'))
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), 'exec'), namespace)
        event = SimpleNamespace(message=SimpleNamespace(text='뉴스 **본문**', id=7),
                                get_chat=AsyncMock(return_value=SimpleNamespace(title='테스트')))
        return namespace['handler'], event, client, classify

    async def test_accepted_message_is_sent_as_plain_text(self):
        run, event, client, _ = self.setup_handler('합격')
        await run(event)
        client.send_message.assert_awaited_once_with(-123, '⭐️ [AI 추천 뉴스 - 테스트]\n\n뉴스 **본문**', parse_mode=None)

    async def test_rejection_and_ai_failure_do_not_send(self):
        for verdict in ('불합격', None):
            run, event, client, _ = self.setup_handler(verdict)
            with self.assertLogs('test', level='INFO'):
                await run(event)
            client.send_message.assert_not_awaited()

    async def test_empty_message_is_not_classified(self):
        run, event, client, classify = self.setup_handler('합격')
        event.message.text = None
        await run(event)
        classify.assert_not_awaited()
        client.send_message.assert_not_awaited()

    async def test_send_failure_is_logged(self):
        run, event, client, _ = self.setup_handler('합격')
        client.send_message.side_effect = RuntimeError('no permission')
        with self.assertLogs('test', level='ERROR') as logs:
            await run(event)
        self.assertIn('전송 실패', logs.output[0])
