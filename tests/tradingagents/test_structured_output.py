import importlib.util
import unittest
from pathlib import Path

module_path = Path(__file__).resolve().parents[2] / "tradingagents" / "utils" / "structured_output.py"
spec = importlib.util.spec_from_file_location("structured_output_under_test", module_path)
structured_output = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(structured_output)


class StructuredOutputTests(unittest.TestCase):
    def test_extract_json_text_from_fenced_block(self):
        text = 'prefix\n```json\n{"stocks": [{"code": "000001"}]}\n```\nsuffix'

        self.assertEqual(
            structured_output.extract_json_text(text),
            '{"stocks": [{"code": "000001"}]}',
        )

    def test_strip_structured_payload_blocks_keeps_report_text(self):
        text = """正文

```json
{"industry_logic_sections": {"policy": "p"}}
```
"""

        cleaned = structured_output.strip_structured_payload_blocks(text)

        self.assertEqual(cleaned, "正文")


if __name__ == "__main__":
    unittest.main()
