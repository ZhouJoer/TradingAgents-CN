#!/usr/bin/env python3
"""
将当前本地活跃配置切换为 MiniMax。

用途：
1. 仅修改当前机器的数据库配置和 legacy settings.json
2. 不修改仓库默认导入逻辑
3. 方便本地开发环境在需要时手动切到 MiniMax

示例：
    python scripts/set_local_minimax_config.py
    python scripts/set_local_minimax_config.py --dry-run
    python scripts/set_local_minimax_config.py --quick-model MiniMax-M2.5-highspeed --deep-model MiniMax-M2.5
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_QUICK_MODEL = "MiniMax-M2.7-highspeed"
DEFAULT_DEEP_MODEL = "MiniMax-M2.7"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="切换当前本地配置到 MiniMax")
    parser.add_argument("--quick-model", default=DEFAULT_QUICK_MODEL, help="快速分析模型")
    parser.add_argument("--deep-model", default=DEFAULT_DEEP_MODEL, help="深度分析模型")
    parser.add_argument("--base-url", default="", help="MiniMax Base URL，默认读取 MINIMAX_BASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="仅打印目标配置，不写入数据库")
    return parser.parse_args()


def resolve_base_url(cli_value: str) -> str:
    return (cli_value or os.getenv("MINIMAX_BASE_URL") or DEFAULT_BASE_URL).strip()


def require_minimax_api_key() -> str:
    api_key = (os.getenv("MINIMAX_API_KEY") or "").strip()
    if not api_key or api_key.startswith("your_"):
        raise RuntimeError("未检测到有效的 MINIMAX_API_KEY，请先在 .env 中配置后再执行脚本")
    return api_key


def build_provider_document(base_url: str) -> dict[str, Any]:
    from tradingagents.llm_clients.provider_keys import canonical_aliases

    return {
        "name": "minimax",
        "display_name": "MiniMax",
        "description": "MiniMax 独立厂商配置（本地脚本写入）",
        "website": "https://www.minimaxi.com/",
        "api_doc_url": "https://www.minimaxi.com/document",
        "logo_url": None,
        "is_active": True,
        "supported_features": ["chat", "completion", "function_calling", "streaming", "vision"],
        "default_base_url": base_url,
        "api_key": "",
        "api_secret": "",
        "aliases": canonical_aliases("minimax"),
        "extra_config": {
            "managed_by": "scripts/set_local_minimax_config.py",
            "api_style": "provider_native_env",
        },
    }


def build_catalog_document(quick_model: str, deep_model: str) -> dict[str, Any]:
    return {
        "provider": "minimax",
        "provider_name": "MiniMax",
        "models": [
            {
                "name": quick_model,
                "display_name": quick_model,
                "description": "MiniMax 快速分析模型",
                "context_length": 1_000_000,
                "max_tokens": 8000,
                "input_price_per_1k": None,
                "output_price_per_1k": None,
                "currency": "CNY",
                "is_deprecated": False,
                "release_date": None,
                "capabilities": ["tool_calling", "fast_response"],
                "original_provider": "minimax",
                "original_model": quick_model,
            },
            {
                "name": deep_model,
                "display_name": deep_model,
                "description": "MiniMax 深度分析模型",
                "context_length": 1_000_000,
                "max_tokens": 12000,
                "input_price_per_1k": None,
                "output_price_per_1k": None,
                "currency": "CNY",
                "is_deprecated": False,
                "release_date": None,
                "capabilities": ["tool_calling", "reasoning", "long_context"],
                "original_provider": "minimax",
                "original_model": deep_model,
            },
        ],
    }


def build_llm_config(model_name: str, base_url: str, *, quick: bool):
    from app.models.config import LLMConfig

    return LLMConfig(
        provider="minimax",
        model_name=model_name,
        model_display_name=model_name,
        api_key="",
        api_base=base_url,
        max_tokens=8000 if quick else 12000,
        temperature=0.7,
        timeout=180,
        retry_times=3,
        enabled=True,
        description="MiniMax 本地开发配置",
        model_category="openai_compatible",
        custom_endpoint=base_url,
        enable_memory=False,
        enable_debug=False,
        priority=20 if quick else 30,
        input_price_per_1k=None,
        output_price_per_1k=None,
        currency="CNY",
        capability_level=3 if quick else 4,
        suitable_roles=["quick_analysis"] if quick else ["deep_analysis"],
        features=["tool_calling", "fast_response"] if quick else ["tool_calling", "reasoning", "long_context"],
        recommended_depths=["快速", "基础", "标准"] if quick else ["标准", "深度", "全面"],
        performance_metrics={"speed": 5, "cost": 4, "quality": 4} if quick else {"speed": 4, "cost": 4, "quality": 5},
    )


async def apply_minimax_config(args: argparse.Namespace) -> None:
    from app.core.database import close_db, init_db
    from app.core.unified_config import unified_config
    from app.services.config_service import ConfigService

    load_dotenv(PROJECT_ROOT / ".env", override=True)
    require_minimax_api_key()

    base_url = resolve_base_url(args.base_url)
    quick_model = args.quick_model.strip()
    deep_model = args.deep_model.strip()

    print("=" * 72)
    print("🚀 本地 MiniMax 配置脚本")
    print("=" * 72)
    print(f"  Base URL : {base_url}")
    print(f"  Quick    : {quick_model}")
    print(f"  Deep     : {deep_model}")
    print(f"  Dry Run  : {args.dry_run}")

    await init_db()
    try:
        service = ConfigService()
        db = await service._get_db()
        system_config = await service.get_system_config()
        if not system_config:
            raise RuntimeError("未找到当前系统配置，无法切换 MiniMax")

        provider_doc = build_provider_document(base_url)
        catalog_doc = build_catalog_document(quick_model, deep_model)
        quick_config = build_llm_config(quick_model, base_url, quick=True)
        deep_config = build_llm_config(deep_model, base_url, quick=False)

        if args.dry_run:
            print("\n[Dry Run] 不写入数据库，仅展示目标变更：")
            print(f"  default_provider      -> minimax")
            print(f"  default_llm           -> {quick_model}")
            print(f"  quick_analysis_model  -> {quick_model}")
            print(f"  deep_analysis_model   -> {deep_model}")
            print(f"  llm_provider doc      -> {provider_doc['name']} ({provider_doc['default_base_url']})")
            print(f"  model_catalog provider-> {catalog_doc['provider']}")
            return

        await db.llm_providers.update_one(
            {"name": "minimax"},
            {"$set": provider_doc},
            upsert=True,
        )
        await db.model_catalog.update_one(
            {"provider": "minimax"},
            {"$set": catalog_doc},
            upsert=True,
        )

        llm_configs = [cfg for cfg in (system_config.llm_configs or []) if cfg.model_name not in {quick_model, deep_model}]
        llm_configs.extend([quick_config, deep_config])

        system_config.llm_configs = llm_configs
        system_config.default_llm = quick_model
        system_config.system_settings = dict(system_config.system_settings or {})
        system_config.system_settings["default_provider"] = "minimax"
        system_config.system_settings["default_model"] = quick_model
        system_config.system_settings["quick_analysis_model"] = quick_model
        system_config.system_settings["deep_analysis_model"] = deep_model

        ok = await service.save_system_config(system_config)
        if not ok:
            raise RuntimeError("保存系统配置失败")

        unified_config.sync_to_legacy_format(system_config)

        latest = await service.get_system_config()
        print("\n✅ 已切换当前本地配置到 MiniMax")
        print(f"  default_provider      : {latest.system_settings.get('default_provider')}")
        print(f"  default_llm           : {latest.default_llm}")
        print(f"  quick_analysis_model  : {latest.system_settings.get('quick_analysis_model')}")
        print(f"  deep_analysis_model   : {latest.system_settings.get('deep_analysis_model')}")
        print("\n现在可直接启动后端/前端进行本地联调。")
    finally:
        await close_db()


def main() -> None:
    args = parse_args()
    asyncio.run(apply_minimax_config(args))


if __name__ == "__main__":
    main()
