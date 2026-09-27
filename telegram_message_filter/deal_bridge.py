"""Authenticated Android notification intake using the existing Telegram connection."""
import asyncio
from contextlib import suppress
import hashlib
import hmac
import json
import logging
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import urlsplit, urlunsplit

from aiohttp import web

from deal_filter import Listing, evaluate, load_watchlist, render_alert

logger = logging.getLogger(__name__)


def listing_from_notification(raw, config):
    """Only use explicit facts in the notification; never assume missing price/region/status."""
    if '산본2동' not in raw or config['region']['id'] != 1635:
        return None, '알림에서 산본2동을 확인하지 못함'
    prices = set()
    for match in re.finditer(r'(?<![\d.])([0-9][0-9,]*(?:\.[0-9]+)?)\s*(만)?\s*원', raw):
        from decimal import Decimal
        value = Decimal(match[1].replace(',', '')) * (10000 if match[2] else 1)
        if value == int(value):
            prices.add(int(value))
    if len(prices) != 1:
        return None, '알림의 판매가격이 없거나 여러 가격으로 모호함'
    if re.search(r'판매\s*완료|거래\s*완료|예약\s*중', raw):
        return None, '예약/거래 완료 알림'
    if not re.search(r'판매\s*중|판매합니다|판매해요', raw):
        return None, '알림에서 판매 중 상태를 확인하지 못함'
    urls = re.findall(r'https://www\.daangn\.com/kr/buy-sell/[^\s<>"\']+', raw)
    url = ''
    if urls:
        parsed = urlsplit(urls[0].rstrip(').,'))
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
    title_lines = [line.strip() for line in raw.splitlines() if line.strip() and not line.startswith('https://')]
    # Retain all notification lines for accessory/model exclusions as well as matching.
    title = ' '.join(title_lines)[:1000]
    identity = url or hashlib.sha256(raw.encode()).hexdigest()
    return Listing(identity, url, title, raw, prices.pop(), 1635, 'on_sale'), ''


class DealInbox:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('''CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
            raw TEXT NOT NULL, created REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            reason TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
            retry_at REAL NOT NULL DEFAULT 0)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS sent_deals (
            listing_id TEXT NOT NULL, price INTEGER NOT NULL, sent REAL NOT NULL,
            PRIMARY KEY (listing_id, price))''')
        self.db.commit()

    def accept(self, raw):
        fingerprint = hashlib.sha256(re.sub(r'\s+', ' ', raw).strip().encode()).hexdigest()
        existing = self.db.execute('SELECT id FROM notifications WHERE fingerprint=?', (fingerprint,)).fetchone()
        if existing:
            return existing['id'], False
        if self.db.execute("SELECT count(*) FROM notifications WHERE state='pending'").fetchone()[0] >= 1000:
            raise OverflowError('수신 대기열이 가득 찼습니다.')
        cursor = self.db.execute('INSERT INTO notifications(fingerprint,raw,created) VALUES (?,?,?)',
                                 (fingerprint, raw, time.time()))
        self.db.commit()
        return cursor.lastrowid, True

    def pending(self):
        return self.db.execute("SELECT * FROM notifications WHERE state='pending' AND retry_at <= ? ORDER BY id LIMIT 5",
                               (time.time(),)).fetchall()

    def finish(self, row_id, state, reason):
        self.db.execute('UPDATE notifications SET state=?,reason=? WHERE id=?', (state, reason[:500], row_id))
        self.db.commit()

    def seen(self, listing):
        return self.db.execute('SELECT 1 FROM sent_deals WHERE listing_id=? AND price=?',
                               (listing.id, listing.price)).fetchone() is not None

    def sent(self, listing):
        self.db.execute('INSERT OR IGNORE INTO sent_deals VALUES (?,?,?)', (listing.id, listing.price, time.time()))
        self.db.commit()

    def retry(self, row):
        attempts = row['attempts'] + 1
        self.db.execute('UPDATE notifications SET attempts=?, state=?, reason=?, retry_at=? WHERE id=?',
                        (attempts, 'failed' if attempts >= 3 else 'pending', 'Telegram 전송 실패',
                         time.time() + 30 * 2 ** attempts, row['id']))
        self.db.commit()

    def prune(self):
        self.db.execute('DELETE FROM notifications WHERE created < ?', (time.time() - 7 * 86400,))
        self.db.execute('DELETE FROM sent_deals WHERE sent < ?', (time.time() - 90 * 86400,))
        self.db.commit()

    def status(self):
        counts = dict(self.db.execute('SELECT state,count(*) FROM notifications GROUP BY state'))
        recent = [dict(row) for row in self.db.execute('SELECT id,state,reason FROM notifications ORDER BY id DESC LIMIT 5')]
        return {'counts': counts, 'recent': recent}

    def close(self):
        self.db.close()


class DealBridge:
    def __init__(self, config_path, db_path, token, send):
        if len(token) < 32:
            raise ValueError('DEALS_WEBHOOK_TOKEN은 무작위 32자 이상이어야 합니다.')
        load_watchlist(config_path)
        self.config_path, self.token, self.send = config_path, token, send
        self.inbox = DealInbox(db_path)
        self.runner = None
        self.task = None
        self.lock = asyncio.Lock()

    async def process_once(self):
        async with self.lock:
            config = load_watchlist(self.config_path)
            self.inbox.prune()
            for row in self.inbox.pending():
                if row['created'] < time.time() - 86400:
                    self.inbox.finish(row['id'], 'rejected', '24시간 지난 알림')
                    continue
                listing, reason = listing_from_notification(row['raw'], config)
                if listing is None:
                    self.inbox.finish(row['id'], 'insufficient', reason)
                    continue
                match = None
                for item in config['items']:
                    accepted, reason = evaluate(listing, item, config)
                    if accepted:
                        match = item
                        break
                if not match:
                    self.inbox.finish(row['id'], 'rejected', reason)
                    continue
                if not config['enabled']:
                    self.inbox.finish(row['id'], 'preview', '조건 통과 (알림 비활성, 전송 안 함)')
                    continue
                if self.inbox.seen(listing):
                    self.inbox.finish(row['id'], 'duplicate', '같은 매물·가격 이미 전송')
                    continue
                try:
                    await asyncio.wait_for(self.send(render_alert(listing, match, config)), timeout=30)
                except Exception:
                    logger.exception('당근 알림 전송 실패: notification_id=%s', row['id'])
                    self.inbox.retry(row)
                    continue
                self.inbox.sent(listing)
                self.inbox.finish(row['id'], 'sent', match['name'])
                logger.info('당근 알림 전송 완료: notification_id=%s item=%s', row['id'], match['id'])

    def _authorize(self, request):
        received = request.headers.get('Authorization', '')
        if not hmac.compare_digest(received.encode(), ('Bearer ' + self.token).encode()):
            raise web.HTTPUnauthorized()

    def application(self):
        app = web.Application(client_max_size=32768)

        async def receive(request):
            self._authorize(request)
            if request.headers.get('X-Notification-App') != 'com.towneers.www':
                raise web.HTTPBadRequest(text='당근 알림만 허용합니다.')
            if request.content_type != 'text/plain':
                raise web.HTTPUnsupportedMediaType(text='text/plain 본문을 사용하세요.')
            try:
                raw = (await asyncio.wait_for(request.text(), timeout=10)).strip()
            except (UnicodeError, TimeoutError):
                raise web.HTTPBadRequest(text='본문 읽기 실패')
            if not 1 <= len(raw) <= 16000:
                raise web.HTTPBadRequest(text='알림 길이 오류')
            try:
                row_id, added = self.inbox.accept(raw)
            except OverflowError:
                raise web.HTTPTooManyRequests()
            return web.json_response({'id': row_id, 'accepted': added}, status=202)

        async def status(request):
            self._authorize(request)
            config = load_watchlist(self.config_path)
            return web.json_response(dict(self.inbox.status(), enabled=config['enabled']))

        app.router.add_post('/deals/notification', receive)
        app.router.add_get('/deals/status', status)
        return app

    async def start(self, host='0.0.0.0', port=8090):
        self.runner = web.AppRunner(self.application(), access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, host, port).start()
        self.task = asyncio.create_task(self._worker())
        logger.info('당근 알림 수신 서버 시작: port=%s (실제 전송은 watchlist enabled 설정에 따름)', port)

    async def _worker(self):
        while True:
            try:
                await self.process_once()
            except Exception:
                logger.exception('당근 알림 처리 오류')
            await asyncio.sleep(2)

    async def close(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        if self.runner:
            await self.runner.cleanup()
        self.inbox.close()
