import asyncio
from datetime import datetime
from decimal import Decimal
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).parents[1] / 'telegram_message_filter'))
from bond_monitor import changes, classify, parse_news, BondMonitor, KIS, KST, NoTradingHistory, DataNotReady, KISRequestError


class BondTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_empty_history_is_cached_and_legacy_errors_are_ignored(self):
        monitor = BondMonitor(None, mock=True, dry_run=True)
        try:
            for error in (DataNotReady('waiting'), KISRequestError('server'), ValueError('schema')):
                monitor._mark_unavailable('MOCK', '20260930', error)
                self.assertFalse(monitor._unavailable_today('MOCK', '20260930'))
            with patch.object(monitor, 'process', AsyncMock(side_effect=NoTradingHistory('EMPTY_HISTORY'))) as process:
                await monitor.run_once()
                await monitor.run_once()
                self.assertEqual(process.await_count, 1)
            self.assertFalse(monitor._unavailable_today('MOCK', '20990101'))
        finally:
            monitor.db.close()

    async def test_intraday_data_retries_without_daily_blacklist(self):
        monitor = BondMonitor(None, mock=True, dry_run=True)
        try:
            with patch.object(monitor, 'process', AsyncMock(side_effect=[DataNotReady('waiting'), None])) as process:
                await monitor.run_once()
                await monitor.run_once()
                self.assertEqual(process.await_count, 2)
            self.assertEqual(monitor.db.execute('SELECT count(*) FROM unavailable').fetchone()[0], 0)
        finally:
            monitor.db.close()

    async def test_account_errors_stop_run_without_caching_bonds(self):
        monitor = BondMonitor(None, mock=True, dry_run=True)
        try:
            with patch('bond_monitor.load_watchlist', return_value=[{'isin': str(i)} for i in range(10)]), patch.object(monitor, 'process', AsyncMock(side_effect=KISRequestError('rate limit'))) as process:
                await monitor.run_once()
                self.assertEqual(process.await_count, 3)
            self.assertEqual(monitor.db.execute('SELECT count(*) FROM unavailable').fetchone()[0], 0)
        finally:
            monitor.db.close()

    def test_exact_boundaries_and_units(self):
        self.assertTrue(changes(9800, 10000)[2])
        self.assertFalse(changes(9801, 10000, '4.999', '4.5')[2])
        self.assertTrue(changes(10000, 10000, '5.0', '4.5')[2])
        self.assertEqual(changes(10000, 10000, '5.0', '4.5')[1], Decimal('50'))
        self.assertFalse(changes(10100, 10000, '4.0', '4.5')[2])
        for price in (0, 'NaN', 'Infinity'):
            with self.assertRaises(ValueError):
                changes(price, 10000)

    async def test_strict_classifier(self):
        ai = SimpleNamespace(chat=AsyncMock(return_value=SimpleNamespace(message=SimpleNamespace(content='부도위험 설명'))))
        self.assertIsNone(await classify(ai, {}, [{'title': 'data'}]))
        ai.chat.return_value.message.content = '수급이슈'
        self.assertEqual(await classify(ai, {}, [{'title': 'data'}]), '수급이슈')
        self.assertIsNone(await classify(ai, {}, []))
        self.assertEqual(ai.chat.call_args.kwargs['options']['temperature'], 0)

    def test_news_dates_and_dedup(self):
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M')
        row = f'<dl><dt class="articleSubject"><a href="/news/read.naver?id=1">예시회사 실적</a></dt><dd><span class="wdate">{now}</span></dd></dl>'
        self.assertEqual(len(parse_news(row * 2, '예시회사')), 1)
        self.assertEqual(parse_news(row, '다른회사'), [])
        self.assertEqual(parse_news(row.replace(now, '2000-01-01 00:00'), '예시회사'), [])

    def test_kis_stale_and_zero_volume(self):
        with patch.dict(os.environ, KIS_APP_KEY='test', KIS_APP_SECRET='test'):
            kis = KIS()
        today = datetime.now(KST).strftime('%Y%m%d')
        rows = [{'stck_bsop_date': today, 'bond_prpr': '9800', 'acml_vol': '1'},
                {'stck_bsop_date': '20000101', 'bond_prpr': '10000', 'acml_vol': '1'}]
        with patch.object(kis, 'get', side_effect=[rows, {'ernn_rate': '5'}]):
            self.assertEqual(kis.collect('TEST')['yield'], '5')
        rows[0]['acml_vol'] = '0'
        with patch.object(kis, 'get', return_value=rows), self.assertRaises(ValueError):
            kis.collect('TEST')
        rows[0]['stck_bsop_date'] = '20000102'
        with patch.object(kis, 'get', return_value=rows), self.assertRaises(ValueError):
            kis.collect('TEST')

    async def test_send_dedup_and_failure(self):
        with patch.dict(os.environ, BOND_DB_PATH=':memory:'):
            send = AsyncMock(side_effect=RuntimeError('send failure'))
            monitor = BondMonitor(send, mock=True)
        bond = {'isin': 'TEST', 'name': 'Test', 'issuer': 'Test'}
        try:
            with patch('bond_monitor.classify', AsyncMock(return_value='외부매크로')):
                with self.assertRaises(RuntimeError):
                    await monitor.process(bond)
                self.assertEqual(monitor.db.execute('SELECT count(*) FROM sent').fetchone()[0], 0)
                send.side_effect = None
                await monitor.process(bond)
                await monitor.process(bond)
                self.assertEqual(send.await_count, 2)
        finally:
            monitor.db.close()
