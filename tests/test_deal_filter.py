from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).parents[1] / 'telegram_message_filter'))
from deal_filter import Listing, evaluate, load_watchlist, render_alert
from deal_test_config import CONFIG


class DealTests(unittest.TestCase):
    def setUp(self):
        self.config = load_watchlist(self._write_config())
        self.watch, self.speaker, self.laptop = self.config['items']
        self.listing = Listing('test', 'https://www.daangn.com/kr/buy-sell/test/',
                               '예시 시계 44mm 미개봉', '선물 받았고 미개봉입니다.', 50000, 1, 'on_sale')

    def _write_config(self):
        path = Path(self.id().replace('.', '_') + '.json')
        path.write_text(json.dumps(deepcopy(CONFIG), ensure_ascii=False))
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_price_boundary(self):
        self.assertTrue(evaluate(self.listing, self.watch, self.config)[0])
        self.assertFalse(evaluate(replace(self.listing, price=50001), self.watch, self.config)[0])

    def test_other_region_unknown_status_and_deposit_are_excluded(self):
        for changes in ({'region_id': 1634}, {'status': 'reserved'}, {'status': 'sold'},
                        {'status': 'unknown'}, {'price': 0}, {'price': True}, {'description': '예약금 10만원입니다'}):
            self.assertFalse(evaluate(replace(self.listing, **changes), self.watch, self.config)[0])

    def test_wrong_model_or_accessory_is_excluded(self):
        for title in ('예시 시계 40mm 미개봉', '예시 시계 프로 44mm 미개봉',
                      '예시 시계 44mm 스트랩 미개봉', '다른 시계 44mm 미개봉'):
            self.assertFalse(evaluate(replace(self.listing, title=title), self.watch, self.config)[0])

    def test_used_and_unopened_like_are_excluded(self):
        for description in ('개봉 후 미사용입니다', '미개봉급입니다', '미개봉 아님', '미개봉 아닙니다', '미 개봉 급', '한 번 사용했어요', '씰 제거했습니다'):
            self.assertFalse(evaluate(replace(self.listing, description=description), self.watch, self.config)[0])
        listing = replace(self.listing, title='예시 시계 44mm', description='미사용 새상품입니다')
        self.assertFalse(evaluate(listing, self.watch, self.config)[0])

    def test_speaker_limit(self):
        speaker = replace(self.listing, title='예시 스피커 미개봉', price=40000)
        self.assertTrue(evaluate(speaker, self.speaker, self.config)[0])
        self.assertFalse(evaluate(replace(speaker, price=40001), self.speaker, self.config)[0])

    def test_arm_evidence_and_laptop_limit(self):
        laptop = replace(self.listing, title='예시 ARM 노트북 미개봉', price=500000)
        self.assertTrue(evaluate(laptop, self.laptop, self.config)[0])
        self.assertFalse(evaluate(replace(laptop, price=500001), self.laptop, self.config)[0])
        self.assertFalse(evaluate(replace(laptop, title='예시 ARM 태블릿 미개봉'), self.laptop, self.config)[0])
        self.assertFalse(evaluate(replace(laptop, title='예시 인텔 노트북 미개봉'), self.laptop, self.config)[0])
        self.assertFalse(evaluate(replace(laptop, title='예시 노트북 미개봉'), self.laptop, self.config)[0])

    def test_alert_discloses_manual_reference_and_seller_claim(self):
        message = render_alert(self.listing, self.watch, self.config)
        self.assertIn('50,000원', message)
        self.assertIn('100,000원', message)
        self.assertIn('50.0%', message)
        self.assertIn('실물 확인 전', message)
        self.assertIn('실시간 거래 시세를 조회한 값이 아닙니다', message)

    def test_live_collection_is_not_falsely_enabled(self):
        self.assertFalse(self.config['enabled'])
