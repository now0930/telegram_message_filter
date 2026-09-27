import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parents[1] / 'telegram_message_filter'))
from deal_bridge import DealBridge, listing_from_notification
from deal_filter import load_watchlist
from aiohttp.test_utils import TestClient, TestServer

BASE = Path(__file__).parents[1] / 'telegram_message_filter' / 'deal_watchlist.json'
RAW = '갤럭시 워치9 44mm 미개봉\n경기도 군포시 산본2동 판매중\n255,000원\nhttps://www.daangn.com/kr/buy-sell/test/'
TOKEN = 'a' * 40


class NotificationTests(unittest.TestCase):
    def test_explicit_fields_and_korean_price(self):
        config = load_watchlist(BASE)
        listing, _ = listing_from_notification(RAW.replace('255,000원', '25.5만원'), config)
        self.assertEqual(listing.price, 255000)
        self.assertEqual(listing.region_id, 1635)

    def test_missing_ambiguous_or_sold_is_not_assumed(self):
        config = load_watchlist(BASE)
        for text in (RAW.replace('산본2동', '산본1동'), RAW.replace('판매중', ''),
                     RAW.replace('판매중', '거래완료'), RAW + '\n정가 510,000원', RAW.replace('255,000원', '')):
            self.assertIsNone(listing_from_notification(text, config)[0])


class WebhookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'config.json'
        self.path.write_text(BASE.read_text())
        self.send = AsyncMock()
        self.bridge = DealBridge(str(self.path), str(Path(self.temp.name) / 'inbox.sqlite3'), TOKEN, self.send)
        self.client = TestClient(TestServer(self.bridge.application()))
        await self.client.start_server()
        self.headers = {'Authorization': 'Bearer ' + TOKEN, 'X-Notification-App': 'com.towneers.www', 'Content-Type': 'text/plain; charset=utf-8'}

    async def asyncTearDown(self):
        await self.client.close()
        await self.bridge.close()
        self.temp.cleanup()

    def enable(self):
        config = json.loads(self.path.read_text()); config['enabled'] = True
        self.path.write_text(json.dumps(config))

    async def test_authentication_and_app_scope(self):
        response = await self.client.post('/deals/notification', data=RAW)
        self.assertEqual(response.status, 401)
        response = await self.client.post('/deals/notification', data=RAW, headers=dict(self.headers, **{'X-Notification-App': 'other.app'}))
        self.assertEqual(response.status, 400)
        response = await self.client.get('/deals/status')
        self.assertEqual(response.status, 401)
        self.assertEqual(self.bridge.inbox.status()['counts'], {})

    async def test_preview_persists_but_does_not_send(self):
        response = await self.client.post('/deals/notification', data=RAW.encode(), headers=self.headers)
        self.assertEqual(response.status, 202)
        await self.bridge.process_once()
        self.send.assert_not_awaited()
        self.assertEqual(self.bridge.inbox.status()['counts'], {'preview': 1})

    async def test_enabled_notification_sends_once_and_persists(self):
        self.enable()
        for _ in range(2):
            await self.client.post('/deals/notification', data=RAW.encode(), headers=self.headers)
            await self.bridge.process_once()
        self.send.assert_awaited_once()
        self.assertIn('255,000원', self.send.call_args.args[0])
        await self.client.post('/deals/notification', data=(RAW+'\n재알림').encode(), headers=self.headers)
        await self.bridge.process_once()
        self.send.assert_awaited_once()
        self.assertEqual(self.bridge.inbox.status()['counts'], {'sent': 1, 'duplicate': 1})

    async def test_incomplete_notification_is_recorded_without_fabrication(self):
        self.enable()
        await self.client.post('/deals/notification', data='갤럭시 워치9 새 알림'.encode(), headers=self.headers)
        await self.bridge.process_once()
        self.send.assert_not_awaited()
        self.assertEqual(self.bridge.inbox.status()['counts'], {'insufficient': 1})

    async def test_failed_send_is_retryable(self):
        self.enable(); self.send.side_effect = RuntimeError('temporary')
        await self.client.post('/deals/notification', data=RAW.encode(), headers=self.headers)
        with self.assertLogs('deal_bridge', level='ERROR'):
            await self.bridge.process_once()
        row = self.bridge.inbox.db.execute('SELECT * FROM notifications').fetchone()
        self.assertEqual(row['state'], 'pending')
        self.assertEqual(row['attempts'], 1)
        self.assertEqual(self.bridge.inbox.db.execute('SELECT count(*) FROM sent_deals').fetchone()[0], 0)
        self.bridge.inbox.db.execute('UPDATE notifications SET retry_at=0'); self.bridge.inbox.db.commit()
        self.send.side_effect = None
        await self.bridge.process_once()
        self.assertEqual(self.bridge.inbox.status()['counts'], {'sent': 1})

    async def test_old_notifications_do_not_send(self):
        self.enable()
        await self.client.post('/deals/notification', data=RAW.encode(), headers=self.headers)
        self.bridge.inbox.db.execute('UPDATE notifications SET created=created-90000'); self.bridge.inbox.db.commit()
        await self.bridge.process_once()
        self.send.assert_not_awaited()
        self.assertEqual(self.bridge.inbox.status()['counts'], {'rejected': 1})

    async def test_missing_link_can_still_show_original_app_instruction(self):
        self.enable()
        await self.client.post('/deals/notification', data=RAW.split('https:')[0].encode(), headers=self.headers)
        await self.bridge.process_once()
        self.assertIn('당근 앱의 원본 알림', self.send.call_args.args[0])

    async def test_excessive_body_is_rejected(self):
        response = await self.client.post('/deals/notification', data='x'*40000, headers=self.headers)
        self.assertEqual(response.status, 413)
