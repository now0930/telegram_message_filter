import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parents[1] / 'telegram_message_filter'))
from news_filter import History, NewsFilter, fingerprint, qualifies, render_brief, validate_analysis


def analysis(**changes):
    value = dict(topic='AI반도체·HBM·HBF', importance=4, depth=3, evidence=4, promotional=False,
                 title='AI 반도체 공급 확대', facts=['회사가 공급량을 30% 확대한다고 발표했다.'],
                 why_it_matters='공급 제약 완화 가능성.', uncertainty='실제 출하량은 확인 필요.',
                 reason='공식 공급계획과 전년 대비 수치가 있다.')
    value.update(changes)
    return value


class SelectionTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertTrue(qualifies(analysis()))
        for changes in ({'topic': '기타'}, {'promotional': True}, {'importance': 3},
                        {'depth': 2}, {'evidence': 2}, {'facts': []}):
            self.assertFalse(qualifies(analysis(**changes), 4))
        self.assertTrue(qualifies(analysis(importance=5, depth=2, evidence=4)))
        self.assertFalse(qualifies(analysis(importance=5, depth=1, evidence=4)))
        self.assertFalse(qualifies(analysis(), 5))

    def test_expanded_selection_keeps_evidence_and_ad_guards(self):
        self.assertTrue(qualifies(analysis(importance=3, depth=2, evidence=3)))
        for change in ({'importance': 2}, {'depth': 1}, {'evidence': 2},
                       {'promotional': True}, {'topic': '기타'}, {'facts': []}):
            self.assertFalse(qualifies(analysis(importance=3, depth=2, evidence=3) | change))
        self.assertFalse(qualifies(analysis(importance=3, depth=2, evidence=3), 4))

    def test_invalid_json_scores_and_fields_fail_closed(self):
        for value in ('합격', '{}', json.dumps(analysis(importance=True)),
                      json.dumps(analysis(depth=6)), json.dumps(analysis(facts='거짓'))):
            with self.assertRaises((ValueError, TypeError)):
                validate_analysis(value)
        self.assertEqual(validate_analysis(json.dumps(analysis())), analysis())

    def test_advertisement_may_have_no_summary(self):
        value = analysis(promotional=True, title='', facts=[], why_it_matters='', uncertainty='')
        self.assertEqual(validate_analysis(json.dumps(value)), value)
        self.assertFalse(qualifies(value))

    def test_existing_history_database_migrates_without_losing_rows(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'legacy.sqlite3')
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE delivered (id INTEGER PRIMARY KEY, fingerprint TEXT, created REAL, analysis TEXT, source TEXT, destination_id INTEGER)')
            import time
            db.execute('INSERT INTO delivered VALUES (1, ?, ?, ?, ?, ?)',
                       (fingerprint('원문'), time.time(), json.dumps(analysis()), 'a/1', 12))
            db.commit(); db.close()
            history = History(path)
            row = history.recent()[0]
            self.assertEqual(row['destination_id'], 12)
            self.assertIsNone(row['portal_verification'])
            history.close()

    def test_fingerprint_preserves_material_numbers(self):
        self.assertEqual(fingerprint('AI  공급\n확대'), fingerprint('ai 공급 확대'))
        self.assertNotEqual(fingerprint('30% 확대'), fingerprint('40% 확대'))

    def test_brief_contains_context_and_source(self):
        brief = render_brief(analysis(), 'https://t.me/test/1', update=True)
        for text in ('중요 후속', '왜 중요한가', '확인할 점', 'https://t.me/test/1'):
            self.assertIn(text, brief)
        self.assertLess(len(brief.encode('utf-16-le')) // 2, 4096)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'history.sqlite3')
        self.history = History(self.path)
        self.ai = SimpleNamespace(chat=AsyncMock())
        self.filter = NewsFilter(self.ai, 'test-model', self.history)
        self.sender = AsyncMock(return_value=SimpleNamespace(id=12))

    async def asyncTearDown(self):
        self.history.close()
        self.temp.cleanup()

    def replies(self, *values):
        self.ai.chat.side_effect = [{'message': {'content': json.dumps(v)}} for v in values]

    async def test_send_and_persist_only_after_success(self):
        self.replies(analysis())
        self.assertIn('전송 완료', await self.filter.process('원문', 'channel/1', self.sender))
        self.sender.assert_awaited_once()
        self.history.close()
        self.history = History(self.path)
        self.filter.history = self.history
        self.assertIn('중복', await self.filter.process('원 문', 'other/1', self.sender))
        self.assertEqual(self.sender.await_count, 1)

    async def test_rejection_is_not_stored(self):
        self.replies(analysis(importance=2))
        self.assertIn('선별 제외', await self.filter.process('잡담', 'channel/1', self.sender))
        self.sender.assert_not_awaited()
        self.assertEqual(len(self.history.recent()), 0)

    async def test_paraphrase_duplicate_across_channels(self):
        self.history.remember('기존 글', analysis(), 'first/1', 1)
        self.replies(analysis(), dict(duplicate_id=1, material_update=False, reason='동일 발표'))
        self.assertIn('같은 사건', await self.filter.process('다른 표현', 'second/2', self.sender))
        self.sender.assert_not_awaited()

    async def test_material_update_is_delivered(self):
        self.history.remember('기존 글', analysis(), 'first/1', 1)
        self.replies(analysis(), dict(duplicate_id=1, material_update=True, reason='계약 확정'))
        await self.filter.process('새 사실', 'second/2', self.sender)
        self.assertIn('중요 후속', self.sender.call_args.args[0])
        self.assertEqual(len(self.history.recent()), 2)

    async def test_different_event_is_not_suppressed(self):
        self.history.remember('지난 분기', analysis(), 'first/1', 1)
        self.replies(analysis(), dict(duplicate_id=0, material_update=False, reason='다른 실적기간'))
        await self.filter.process('이번 분기', 'second/2', self.sender)
        self.sender.assert_awaited_once()

    async def test_bad_duplicate_id_fails_closed(self):
        self.history.remember('기존 글', analysis(), 'first/1', 1)
        self.replies(analysis(), dict(duplicate_id=999, material_update=False, reason='오류'))
        with self.assertRaises(ValueError):
            await self.filter.process('새 글', 'second/2', self.sender)
        self.sender.assert_not_awaited()

    async def test_failed_delivery_can_retry(self):
        self.replies(analysis(), analysis())
        self.sender.side_effect = RuntimeError('전송 실패')
        with self.assertRaises(RuntimeError):
            await self.filter.process('원문', 'channel/1', self.sender)
        self.assertEqual(len(self.history.recent()), 0)
        self.sender.side_effect = None
        await self.filter.process('원문', 'channel/1', self.sender)
        self.assertEqual(len(self.history.recent()), 1)

    async def test_concurrent_identical_posts_send_once(self):
        self.replies(analysis())
        await asyncio.gather(self.filter.process('원문', 'a/1', self.sender),
                             self.filter.process('원문', 'b/2', self.sender))
        self.sender.assert_awaited_once()

    async def test_link_body_used_and_source_preserved(self):
        self.replies(analysis())
        url = 'https://v.daum.net/v/20260927093939078'
        self.filter.portal_verifier = SimpleNamespace(
            linked_articles=AsyncMock(return_value=[dict(url=url, title='기사', body='실제 기사 본문')]),
            requires=lambda *args: False)
        await self.filter.process(url, 'telegram/1', self.sender)
        payload = self.filter.ai.chat.call_args.kwargs['messages'][1]['content']
        self.assertIn('실제 기사 본문', payload)
        self.assertIn(url, self.sender.call_args.args[0])
        self.assertEqual(self.history.recent()[0]['source'], 'telegram/1')
        self.assertEqual(self.filter.ai.chat.call_args.kwargs['options']['num_ctx'], 16384)

    async def test_target_portal_mismatch_prevents_send_and_history(self):
        self.replies(analysis())
        self.filter.portal_verifier = SimpleNamespace(linked_articles=AsyncMock(return_value=[]), requires=lambda *args: True,
            verify=AsyncMock(return_value=(None, '불일치')))
        outcome = await self.filter.process('원문', 'a/1', self.sender, channel_username='best_article')
        self.assertIn('포털 대조 제외', outcome)
        self.sender.assert_not_awaited()
        self.assertEqual(len(self.history.recent()), 0)

    async def test_darthacking_rejects_shallow_or_weakly_sourced_news(self):
        for overrides in ({'importance': 3}, {'depth': 2}, {'evidence': 3}):
            self.replies(analysis(**overrides))
            outcome = await self.filter.process('원문', 'a/1', self.sender,
                                               channel_id=1066938528)
            self.assertIn('채널 엄격 기준 제외', outcome)
        self.sender.assert_not_awaited()
        self.assertEqual(len(self.history.recent()), 0)

    async def test_darthacking_accepts_substantial_sourced_news(self):
        self.replies(analysis(importance=4, depth=3, evidence=4))
        await self.filter.process('원문', 'a/1', self.sender,
                                  channel_username='@Darthacking')
        self.sender.assert_awaited_once()

    async def test_portal_exception_cannot_send(self):
        self.replies(analysis())
        self.filter.portal_verifier = SimpleNamespace(linked_articles=AsyncMock(return_value=[]), requires=lambda *args: True,
            verify=AsyncMock(side_effect=TimeoutError()))
        with self.assertRaises(TimeoutError):
            await self.filter.process('원문', 'a/1', self.sender, channel_id=1030607534)
        self.sender.assert_not_awaited()

    async def test_other_channels_do_not_require_portal_search(self):
        self.replies(analysis())
        verifier = SimpleNamespace(linked_articles=AsyncMock(return_value=[]), requires=lambda *args: False, verify=AsyncMock())
        self.filter.portal_verifier = verifier
        await self.filter.process('원문', 'a/1', self.sender, channel_username='other')
        verifier.verify.assert_not_awaited()
        self.sender.assert_awaited_once()

    async def test_verified_source_is_linked_and_persisted(self):
        self.replies(analysis())
        evidence = dict(url='https://v.daum.net/v/20260927093939078', title='포털 보도', reason='일치')
        self.filter.portal_verifier = SimpleNamespace(linked_articles=AsyncMock(return_value=[]), requires=lambda *args: True,
            verify=AsyncMock(return_value=(evidence, '일치')))
        await self.filter.process('원문', 'a/1', self.sender, channel_username='best_article')
        self.assertIn(evidence['url'], self.sender.call_args.args[0])
        self.assertEqual(json.loads(self.history.recent()[0]['portal_verification']), evidence)

    async def test_expired_records_are_removed(self):
        self.history.remember('원문', analysis(), 'a/1', 1)
        self.history.db.execute('UPDATE delivered SET created = 0')
        self.history.db.commit()
        self.replies(analysis())
        await self.filter.process('원문', 'b/1', self.sender)
        self.sender.assert_awaited_once()

    async def test_older_batches_are_checked(self):
        for i in range(16):
            self.history.remember(str(i), analysis(), f'a/{i}', i)
        self.replies(analysis(), dict(duplicate_id=0, material_update=False, reason='다른 사건'),
                     dict(duplicate_id=1, material_update=False, reason='동일 사건'))
        self.assertIn('같은 사건', await self.filter.process('오래된 사건', 'b/1', self.sender))
        self.sender.assert_not_awaited()
