CONFIG = {
    'enabled': False,
    'region': {'id': 1, 'name': '테스트 지역'},
    'max_price_percent': 50,
    'require_unopened': True,
    'items': [
        {
            'id': 'example_watch',
            'name': '예시 시계',
            'reference_price': 100000,
            'reference_type': 'user_defined_new_price',
            'required_patterns': [r'예시\s*시계', r'44\s*mm'],
            'excluded_title_patterns': [r'스트랩|케이스', r'프로|pro'],
        },
        {
            'id': 'example_speaker',
            'name': '예시 스피커',
            'reference_price': 80000,
            'reference_type': 'user_defined_new_price',
            'required_patterns': [r'예시', r'스피커'],
            'excluded_title_patterns': [r'케이스|부품|이어폰|헤드폰'],
        },
        {
            'id': 'example_laptop',
            'name': '예시 ARM 노트북',
            'reference_price': 1000000,
            'reference_type': 'user_defined_new_price',
            'required_patterns': [r'노트북', r'\barm\b'],
            'excluded_title_patterns': [r'인텔|라이젠|부품|충전기'],
        },
    ],
}
