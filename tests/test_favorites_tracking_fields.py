import unittest
import sys
import types
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

for package_name, package_path in {
    "app": REPO_ROOT / "app",
    "app.models": REPO_ROOT / "app" / "models",
    "app.services": REPO_ROOT / "app" / "services",
    "app.core": REPO_ROOT / "app" / "core",
}.items():
    package = sys.modules.get(package_name)
    if package is None:
        package = types.ModuleType(package_name)
        sys.modules[package_name] = package
    package.__path__ = [str(package_path)]

from app.services.favorites_service import FavoritesService


class FavoritesTrackingFieldsTests(unittest.TestCase):
    def test_format_favorite_includes_tracking_fields_with_defaults(self):
        service = FavoritesService()

        item = service._format_favorite({
            "stock_code": "000001",
            "stock_name": "平安银行",
            "market": "A股",
            "added_at": datetime(2026, 6, 11, 9, 0, 0),
        })

        self.assertEqual(item["watch_reason"], "")
        self.assertIsNone(item["target_price_low"])
        self.assertIsNone(item["target_price_high"])
        self.assertEqual(item["risk_reminder"], "")
        self.assertIsNone(item["next_review_date"])
        self.assertEqual(item["linked_report_ids"], [])
        self.assertFalse(item["message_alert_enabled"])

    def test_sanitize_update_value_allows_clearing_tracking_fields(self):
        service = FavoritesService()

        self.assertEqual(service._sanitize_update_value("linked_report_ids", None), [])
        self.assertEqual(service._sanitize_update_value("watch_reason", None), "")
        self.assertFalse(service._sanitize_update_value("message_alert_enabled", None))
        self.assertIsNone(service._sanitize_update_value("target_price_low", None))


if __name__ == "__main__":
    unittest.main()
