import ast
import logging
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock

source = Path(__file__).parents[1] / 'telegram_message_filter' / 'main.py'
main = next(n for n in ast.parse(source.read_text()).body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == 'main')

class StartupTests(unittest.IsolatedAsyncioTestCase):
    def setup_main(self, entities):
        client = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock(),
            is_user_authorized=AsyncMock(return_value=True), get_dialogs=AsyncMock(),
            get_entity=AsyncMock(side_effect=entities),
            get_input_entity=AsyncMock(return_value=SimpleNamespace(id=-99)),
            add_event_handler=MagicMock(), run_until_disconnected=AsyncMock())
        history = MagicMock()
        events = SimpleNamespace(NewMessage=MagicMock())
        namespace = dict(os=os, History=MagicMock(return_value=history),
            NewsFilter=MagicMock(), PortalVerifier=MagicMock(), ollama_client=None, telegram_client=client,
            target_channels=['@a', '@b'], DESTINATION_CHAT_ID='-99',
            logger=logging.getLogger('startup-test'), handler=AsyncMock(), events=events,
            utils=SimpleNamespace(get_peer_id=lambda entity: entity.id))
        exec(compile(ast.Module(body=[main], type_ignores=[]), str(source), 'exec'), namespace)
        return namespace['main'], client, history, events

    async def test_invalid_channel_does_not_disable_healthy_channel(self):
        channel = SimpleNamespace(id=1, left=False, broadcast=True)
        run, client, history, events = self.setup_main([ValueError('invalid username'), channel])
        with self.assertLogs('startup-test', level='INFO'):
            await run()
        events.NewMessage.assert_called_once_with(chats=[channel])
        client.run_until_disconnected.assert_awaited_once()
        client.disconnect.assert_awaited_once()
        history.close.assert_called_once()

    async def test_unjoined_and_bot_are_not_monitored(self):
        run, client, history, _ = self.setup_main([
            SimpleNamespace(id=1, left=True, broadcast=True),
            SimpleNamespace(id=2, bot=True)])
        with self.assertLogs('startup-test', level='ERROR'), self.assertRaises(RuntimeError):
            await run()
        client.add_event_handler.assert_not_called()
        client.disconnect.assert_awaited_once()
        history.close.assert_called_once()
