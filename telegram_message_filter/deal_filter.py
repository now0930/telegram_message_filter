"""Deterministic deal rules for explicitly described Android notifications."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Listing:
    id: str
    url: str
    title: str
    description: str
    price: int
    region_id: int
    status: str  # Explicitly normalized by a verified source: on_sale/reserved/sold/unknown.


def _validate_item(item, seen_ids):
    """Validate one watchlist item and reject ambiguous configuration early."""
    item_id = item.get('id')
    if not isinstance(item_id, str) or not item_id or item_id in seen_ids:
        raise ValueError('품목 ID 누락 또는 중복')
    seen_ids.add(item_id)
    if not isinstance(item.get('name'), str) or not item['name']:
        raise ValueError('품목 이름 누락')
    if type(item.get('reference_price')) is not int or item['reference_price'] <= 0:
        raise ValueError('기준 가격은 양의 정수여야 합니다.')
    target = item.get('target_price')
    if target is not None and (type(target) is not int or target <= 0):
        raise ValueError('목표 가격은 양의 정수여야 합니다.')
    if item.get('reference_type') != 'user_defined_new_price':
        raise ValueError('지원하지 않는 기준 가격 유형')
    for key in ('required_patterns', 'excluded_title_patterns'):
        patterns = item.get(key)
        if not isinstance(patterns, list) or (key == 'required_patterns' and not patterns):
            raise ValueError('품목 패턴 설정 오류')
        for pattern in patterns:
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError('빈 품목 패턴')
            re.compile(pattern, re.I)


def load_watchlist(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if type(config.get('enabled')) is not bool or config.get('require_unopened') is not True:
        raise ValueError('enabled 및 require_unopened 설정 오류')
    if type(config.get('max_price_percent')) is not int or not 1 <= config['max_price_percent'] <= 50:
        raise ValueError('가격 비율은 1~50 정수여야 합니다.')
    region = config.get('region', {})
    if type(region.get('id')) is not int or not isinstance(region.get('name'), str):
        raise ValueError('지역 설정 오류')
    items = config.get('items')
    if not isinstance(items, list) or not items:
        raise ValueError('관심 품목이 필요합니다.')
    seen = set()
    for item in items:
        _validate_item(item, seen)
    return config


def _price_ceiling(item, config):
    target_price = item.get('target_price')
    if target_price is not None:
        return target_price
    return item['reference_price'] * config['max_price_percent'] // 100


def _has_unopened_evidence(text):
    return bool(re.search(r'미개봉|미\s*개봉|미개봉씰|밀봉|씰\s*미훼손|unopened|factory\s*sealed', text, re.I))


def _contradicts_unopened_claim(text):
    return bool(re.search(
        r'미\s*개봉\s*(?:급|아님|아니|아닙|같은|수준)|개봉\s*(?:후|했|하였|해서|미사용|만|됨|상태)|'
        r'사용\s*(?:했|하였)|전시품|리퍼|중고품|테스트\s*(?:했|하였)|씰\s*(?:훼손|제거)|밀봉\s*(?:훼손|제거)',
        text))


def evaluate(listing, item, config):
    """Fail closed on unavailable status/region, price placeholders, or ambiguous condition."""
    if listing.status != 'on_sale' or listing.region_id != config['region']['id']:
        return False, '판매 중 또는 설정 지역 매물로 확인되지 않음'
    if type(listing.price) is not int or listing.price <= 0:
        return False, '확정 판매가격 없음'
    ceiling = _price_ceiling(item, config)
    if listing.price > ceiling:
        return False, '가격 상한 초과'
    text = listing.title + '\n' + listing.description
    if not all(re.search(pattern, text, re.I) for pattern in item['required_patterns']):
        return False, '모델/사양 일치 근거 부족'
    if any(re.search(pattern, listing.title, re.I) for pattern in item['excluded_title_patterns']):
        return False, '액세서리 또는 제외 모델'
    if re.search(r'삽니다|구매합니다|구매희망|구매\s*원해|구해요|구합니다|예약금|선입금|보증금|계약금|월\s*\d+\s*만?원|렌탈|대여|교환만|가격\s*제안|가격\s*문의', text):
        return False, '구매글/부분 가격/대여 등 제외'
    if _contradicts_unopened_claim(text):
        return False, '개봉/사용 또는 미개봉과 모순되는 설명'
    if not _has_unopened_evidence(text):
        return False, '명시적인 미개봉 근거 없음'
    if item.get('target_price') is not None:
        return True, f"직접 설정한 목표 가격 {ceiling:,}원 이하 및 판매자 미개봉 표기"
    return True, f"설정 기준가의 {config['max_price_percent']}% 이하 및 판매자 미개봉 표기"


def render_alert(listing, item, config):
    parsed = urlsplit(listing.url)
    if listing.url and (parsed.scheme != 'https' or parsed.netloc != 'www.daangn.com' or not parsed.path.startswith('/kr/buy-sell/')):
        raise ValueError('당근 매물 링크가 아닙니다.')
    discount = 100 * (item['reference_price'] - listing.price) / item['reference_price']
    if item.get('target_price') is not None:
        price_rule = f"직접 설정한 목표 가격: {item['target_price']:,}원"
    else:
        price_rule = f"직접 설정한 새제품 기준가: {item['reference_price']:,}원"
    return (f"[당근 가격 알림] {item['name']}\n"
            f"{listing.title[:200]}\n"
            f"지역: {config['region']['name']}\n"
            f"판매가: {listing.price:,}원\n"
            f"{price_rule}\n"
            f"새제품 기준가 대비 {discount:.1f}% 저렴\n"
            "상태: 판매글에 미개봉 표기 (실물 확인 전)\n"
            "기준가는 동일 모델의 실시간 거래 시세를 조회한 값이 아닙니다.\n"
            f"{listing.url or '링크 없음: 당근 앱의 원본 알림에서 확인하세요.'}")
