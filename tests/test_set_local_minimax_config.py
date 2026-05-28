import os
import unittest
from unittest.mock import patch

from scripts import set_local_minimax_config


class LocalMiniMaxConfigScriptTests(unittest.TestCase):
    def test_resolve_base_url_prefers_cli_value(self):
        with patch.dict(os.environ, {"MINIMAX_BASE_URL": "https://env.example/v1"}, clear=False):
            self.assertEqual(
                set_local_minimax_config.resolve_base_url("https://cli.example/v1"),
                "https://cli.example/v1",
            )

    def test_resolve_base_url_falls_back_to_env_then_default(self):
        with patch.dict(os.environ, {"MINIMAX_BASE_URL": "https://env.example/v1"}, clear=False):
            self.assertEqual(
                set_local_minimax_config.resolve_base_url(""),
                "https://env.example/v1",
            )

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                set_local_minimax_config.resolve_base_url(""),
                set_local_minimax_config.DEFAULT_BASE_URL,
            )

    def test_build_provider_document_uses_minimax_aliases(self):
        doc = set_local_minimax_config.build_provider_document("https://api.minimaxi.com/v1")

        self.assertEqual(doc["name"], "minimax")
        self.assertEqual(doc["default_base_url"], "https://api.minimaxi.com/v1")
        self.assertIn("abab", doc["aliases"])
        self.assertIn("mimo", doc["aliases"])
        self.assertEqual(doc["api_key"], "")

    def test_build_catalog_document_contains_quick_and_deep_models(self):
        catalog = set_local_minimax_config.build_catalog_document(
            "MiniMax-M2.7-highspeed",
            "MiniMax-M2.7",
        )

        self.assertEqual(catalog["provider"], "minimax")
        self.assertEqual([item["name"] for item in catalog["models"]], ["MiniMax-M2.7-highspeed", "MiniMax-M2.7"])
