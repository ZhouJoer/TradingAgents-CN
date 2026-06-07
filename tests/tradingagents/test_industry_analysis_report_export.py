import importlib.util
import unittest
from pathlib import Path

module_path = Path(__file__).resolve().parents[2] / "app" / "utils" / "industry_analysis_report.py"
spec = importlib.util.spec_from_file_location("industry_analysis_report_under_test", module_path)
report_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(report_module)


class IndustryAnalysisReportExportTests(unittest.TestCase):
    def test_markdown_export_strips_structured_json_block(self):
        task = {
            "task_id": "task-1",
            "concept": "AI",
            "status": "completed",
            "detail_level": "detailed",
            "result": {
                "candidate_trace": None,
                "due_diligence_report": "行业正文",
                "stock_selection_report": """# Top 5
选股正文

```json
{
  "industry_logic_sections": {"supply_chain": "chain"},
  "stock_selection_sections": {"leaders": "leader"},
  "recommendations": [{"code": "000001", "name": "平安银行"}]
}
```
""",
                "stock_selection_sections": {"leaders": "龙头逻辑"},
                "recommendation_groups": [
                    {
                        "group_key": "stable_leaders",
                        "group_name": "稳健龙头",
                        "description": "低波动",
                        "suitable_style": "稳健",
                        "main_risks": "估值波动",
                        "stocks": [{"code": "000001", "name": "平安银行", "score": 88}],
                    }
                ],
            },
        }

        markdown = report_module.build_industry_markdown_report(task)

        self.assertIn("选股正文", markdown)
        self.assertIn("分组推荐", markdown)
        self.assertIn("稳健龙头", markdown)
        self.assertNotIn("industry_logic_sections", markdown)
        self.assertNotIn("```json", markdown)


if __name__ == "__main__":
    unittest.main()
