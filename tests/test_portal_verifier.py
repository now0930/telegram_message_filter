from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parents[1] / 'telegram_message_filter'))
from portal_verifier import PortalVerifier, article_url, parse_article, search_links

URL = 'https://n.news.naver.com/mnews/article/001/0016337749'
NOW = datetime(2026, 9, 27, 7, tzinfo=timezone.utc)
BODY = '회사는 올해 배터리 생산량을 30% 확대한다고 공식 발표했다. ' * 5


def markup(body=BODY, date='2026-09-27 06:03:01'):
    return f'''<meta property="og:title" content="배터리 공급 확대">
    <span class="_ARTICLE_DATE_TIME" data-date-time="{date}"></span>
    <article id="dic_area"><p>{body}</p><script>광고 숨김</script><br>끝</article>
    <footer>무관한 추천기사</footer>'''


class ParsingTests(unittest.TestCase):
    def test_only_allowed_article_urls(self):
        self.assertEqual(article_url(URL + '?sid=105'), URL)
        self.assertEqual(article_url('http://v.daum.net/v/20260927093939078'),
                         'https://v.daum.net/v/20260927093939078')
        for url in ('http://127.0.0.1/a', 'https://v.daum.net.evil.test/v/20260927093939078',
                    'https://n.news.naver.com@evil.test/mnews/article/001/0016337749',
                    URL.replace('https:', 'file:'), URL.replace('.com/', '.com:443/'),
                    'https://v.daum.net/channel/21/home'):
            self.assertIsNone(article_url(url))

    def test_extract_deduplicated_article_links(self):
        self.assertEqual(search_links(f'<a href="{URL}?a=1&amp;b=2">뉴스</a> {URL}'), [URL])

    def test_naver_article_body_and_date(self):
        result = parse_article(markup(), URL, now=NOW)
        self.assertIn('30%', result['body'])
        self.assertNotIn('광고 숨김', result['body'])
        self.assertNotIn('무관한', result['body'])
        self.assertEqual(result['published'], '2026-09-27T06:03:01+09:00')

    def test_daum_article_body_and_date(self):
        page = f'<meta property="og:title" content="뉴스"><meta property="og:regDate" content="20260927093939"><div class="article_view"><p>{BODY}</p></div>'
        self.assertIsNotNone(parse_article(page, 'https://v.daum.net/v/20260927093939078', now=NOW))

    def test_missing_old_future_or_short_article_is_rejected(self):
        for page in (markup(date=''), markup(date='2025-01-01 00:00:00'),
                     markup(date='2027-01-01 00:00:00'), markup(body='제목만'),
                     markup().replace('dic_area', 'wrong_container')):
            self.assertIsNone(parse_article(page, URL, now=NOW))

    def test_target_by_username_or_stable_id(self):
        verifier = PortalVerifier()
        self.assertTrue(verifier.requires('@BEST_ARTICLE'))
        self.assertTrue(verifier.requires(None, 1030607534))
        self.assertFalse(verifier.requires('best_article_other', 55))


class VerificationTests(unittest.IsolatedAsyncioTestCase):
    def setup_verifier(self, match):
        verifier = PortalVerifier()
        verifier.search = AsyncMock(return_value=[dict(id=1, url=URL, title='생산 확대',
            published='2026-09-27T06:03:01+09:00', body=BODY)])
        ask = AsyncMock(side_effect=[json.dumps({'query': '배터리 생산 확대'}), json.dumps(match)])
        analysis = {'title': '배터리 생산 확대', 'facts': ['생산량을 30% 확대한다.']}
        return verifier, ask, analysis

    def valid_match(self):
        return {'matched': True, 'article_id': 1, 'reason': '동일 생산계획',
                'evidence': [{'fact_index': 0, 'quote': '회사는 올해 배터리 생산량을 30% 확대한다고 공식 발표했다.'}]}

    async def test_match_returns_fetched_url(self):
        verifier, ask, analysis = self.setup_verifier(self.valid_match())
        evidence, _ = await verifier.verify('원문', analysis, ask)
        self.assertEqual(evidence['url'], URL)
        self.assertNotIn('body', evidence)
        self.assertNotIn('quote', evidence)

    async def test_mismatch_does_not_pass(self):
        verifier, ask, analysis = self.setup_verifier(dict(matched=False, article_id=0, reason='수치 다름', evidence=[]))
        evidence, _ = await verifier.verify('생산량 300%', analysis, ask)
        self.assertIsNone(evidence)

    async def test_no_search_results_does_not_call_matching_model(self):
        verifier, ask, analysis = self.setup_verifier(self.valid_match())
        verifier.search.return_value = []
        evidence, _ = await verifier.verify('원문', analysis, ask)
        self.assertIsNone(evidence)
        self.assertEqual(ask.await_count, 1)

    async def test_invented_quote_or_wrong_id_is_rejected(self):
        for changes in ({'article_id': 99}, {'evidence': [{'fact_index': 0, 'quote': '존재하지 않는 그럴듯한 근거입니다.'}]},
                        {'evidence': []}, {'evidence': [{'fact_index': 1, 'quote': BODY[:40]}]}):
            match = self.valid_match(); match.update(changes)
            verifier, ask, analysis = self.setup_verifier(match)
            with self.assertRaises(ValueError):
                await verifier.verify('원문', analysis, ask)

    async def test_search_failure_is_not_a_pass(self):
        verifier, ask, analysis = self.setup_verifier(self.valid_match())
        verifier.search.side_effect = TimeoutError('포털 응답 없음')
        with self.assertRaises(TimeoutError):
            await verifier.verify('원문', analysis, ask)

class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_portal_failure_can_use_other_portal_article(self):
        import httpx
        from unittest.mock import patch
        from portal_verifier import KST
        date = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        def respond(request):
            if request.url.host == 'search.naver.com':
                return httpx.Response(429, text='rate limited')
            if request.url.host == 'search.daum.net':
                return httpx.Response(200, text=f'<a href="{URL}">기사</a>', headers={'content-type': 'text/html'})
            return httpx.Response(200, text=markup(date=date), headers={'content-type': 'text/html'})
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch('portal_verifier.httpx.AsyncClient', return_value=client), self.assertLogs('portal_verifier', level='WARNING'):
            articles = await PortalVerifier().search('배터리 공급')
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]['url'], URL)

    async def test_article_redirect_does_not_fetch_untrusted_target(self):
        import httpx
        from unittest.mock import patch
        visited = []
        def respond(request):
            visited.append(request.url.host)
            if request.url.host.startswith('search.'):
                return httpx.Response(200, text=f'<a href="{URL}">기사</a>', headers={'content-type': 'text/html'})
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=False)
        with patch('portal_verifier.httpx.AsyncClient', return_value=client), self.assertLogs('portal_verifier', level='WARNING'):
            self.assertEqual(await PortalVerifier().search('배터리'), [])
        self.assertNotIn('127.0.0.1', visited)
