import ast
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

source = Path(__file__).parents[1] / 'telegram_message_filter' / 'main.py'
handler = next(n for n in ast.parse(source.read_text()).body
               if isinstance(n, ast.AsyncFunctionDef) and n.name == 'handler')

class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setup_handler(self):
        client = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(id=42)))
        async def process(text, source, send, **kwargs):
            await send('요약: ' + text + '\n' + source)
            return '전송 완료'
        editor = SimpleNamespace(process=AsyncMock(side_effect=process))
        namespace = dict(telegram_client=client, news_filter=editor,
                         DESTINATION_CHAT_ID='-123', logger=logging.getLogger('test'))
        exec(compile(ast.Module(body=[handler], type_ignores=[]), str(source), 'exec'), namespace)
        event = SimpleNamespace(message=SimpleNamespace(text='뉴스', id=7), chat_id=-100123,
                                is_channel=True, get_chat=AsyncMock(return_value=SimpleNamespace(
                                    title='테스트', username='test_channel', id=123)))
        return namespace['handler'], event, client, editor

    async def test_plain_summary_with_public_source(self):
        run, event, client, _ = self.setup_handler()
        await run(event)
        client.send_message.assert_awaited_once_with(-123, '요약: 뉴스\nhttps://t.me/test_channel/7',
                                                    parse_mode=None, link_preview=False)

    async def test_private_source(self):
        run, event, client, _ = self.setup_handler()
        event.get_chat.return_value.username = None
        await run(event)
        self.assertIn('https://t.me/c/123/7', client.send_message.call_args.args[1])

    async def test_empty_message_is_ignored(self):
        run, event, client, editor = self.setup_handler()
        event.message.text = None
        await run(event)
        editor.process.assert_not_awaited()
        client.send_message.assert_not_awaited()

    async def test_error_is_logged(self):
        run, event, client, _ = self.setup_handler()
        client.send_message.side_effect = RuntimeError('no permission')
        with self.assertLogs('test', level='ERROR') as logs:
            await run(event)
        self.assertIn('전송 실패', logs.output[0])
