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
    value = dict(topic='AI', importance=4, depth=3, evidence=4, promotional=False,
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
            self.assertFalse(qualifies(analysis(**changes)))
        self.assertTrue(qualifies(analysis(importance=5, depth=2, evidence=4)))
        self.assertFalse(qualifies(analysis(importance=5, depth=1, evidence=4)))
        self.assertFalse(qualifies(analysis(), 5))

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
