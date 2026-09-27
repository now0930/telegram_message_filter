import ast
from pathlib import Path
import unittest

# Load the pure parser without opening a Telegram session.
source = Path(__file__).parents[1] / 'telegram_message_filter' / 'main.py'
module = ast.parse(source.read_text())
function = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == 'parse_verdict')
namespace = {}
exec('import json\nimport re', namespace)
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
parse = namespace['parse_verdict']

class VerdictTests(unittest.TestCase):
    def test_structured_verdicts(self):
        for verdict in ('합격', '불합격'):
            self.assertEqual(parse('{"verdict": "' + verdict + '"}'), verdict)

    def test_model_language_variants(self):
        for text, expected in [('合格', '합격'), ('不合格', '불합격'), ('**합격**', '합격'), ('불합격', '불합격')]:
            self.assertEqual(parse(text), expected)

    def test_invalid_or_ambiguous_output_is_not_a_rejection(self):
        for text in ('', '합격 불합격', '설명입니다', '{"verdict": null}', '{"verdict": []}', '[]'):
            self.assertIsNone(parse(text))

if __name__ == '__main__':
    unittest.main()
