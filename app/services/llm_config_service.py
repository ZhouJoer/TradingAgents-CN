"""
LLM 模型选择与 provider 配置 — 单股/批量/行业分析共用。
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def resolve_analysis_model_pair(
    quick_model: Optional[str] = None,
    deep_model: Optional[str] = None,
    research_depth: str = "标准",
) -> Tuple[str, str]:
    """
    解析快速/深度分析模型对：用户指定时做能力校验，不合适则回退到自动推荐。
    """
    from app.services.model_capability_service import get_model_capability_service

    capability_service = get_model_capability_service()

    if quick_model and deep_model:
        logger.info("📝 [模型选择] 用户指定模型: quick=%s, deep=%s", quick_model, deep_model)
        validation = capability_service.validate_model_pair(quick_model, deep_model, research_depth)
        for warning in validation["warnings"]:
            if validation["valid"]:
                logger.info(warning)
            else:
                logger.warning(warning)
        if validation["valid"]:
            logger.info("✅ 用户选择的模型验证通过: quick=%s, deep=%s", quick_model, deep_model)
        else:
            logger.warning(
                "⚠️ 用户指定模型未完全满足「%s」分析建议，仍按用户选择执行: quick=%s, deep=%s",
                research_depth,
                quick_model,
                deep_model,
            )
        return quick_model, deep_model

    quick_model, deep_model = capability_service.recommend_models_for_depth(research_depth)
    logger.info("🤖 自动推荐模型: quick=%s, deep=%s", quick_model, deep_model)
    return quick_model, deep_model


def build_llm_provider_config(
    quick_model: Optional[str] = None,
    deep_model: Optional[str] = None,
    research_depth: str = "标准",
) -> dict:
    """
    构建 LLM provider/url/key 配置，供各类分析流水线复用。
    """
    from app.services.simple_analysis_service import get_provider_and_url_by_model_sync

    quick_model, deep_model = resolve_analysis_model_pair(quick_model, deep_model, research_depth)

    quick_provider_info = get_provider_and_url_by_model_sync(quick_model)
    deep_provider_info = get_provider_and_url_by_model_sync(deep_model)

    quick_provider = quick_provider_info["provider"]
    deep_provider = deep_provider_info["provider"]

    logger.info(
        "🔍 快速模型: %s -> provider=%s, url=%s",
        quick_model,
        quick_provider,
        quick_provider_info["backend_url"],
    )
    logger.info(
        "🔍 深度模型: %s -> provider=%s, url=%s",
        deep_model,
        deep_provider,
        deep_provider_info["backend_url"],
    )

    if quick_provider == deep_provider:
        logger.info("✅ 两个模型来自同一厂家: %s", quick_provider)
    else:
        logger.info("✅ 混合模式: quick(%s) + deep(%s)", quick_provider, deep_provider)

    return {
        "llm_provider": quick_provider,
        "quick_think_llm": quick_model,
        "deep_think_llm": deep_model,
        "backend_url": quick_provider_info["backend_url"],
        "api_key": quick_provider_info["api_key"],
        "quick_provider": quick_provider,
        "deep_provider": deep_provider,
        "quick_backend_url": quick_provider_info["backend_url"],
        "deep_backend_url": deep_provider_info["backend_url"],
        "quick_api_key": quick_provider_info["api_key"],
        "deep_api_key": deep_provider_info["api_key"],
        "quick_model_config": {},
        "deep_model_config": {},
        "debug": False,
    }


def is_valid_api_key(api_key: Optional[str]) -> bool:
    """判断 API Key 是否有效（非空且非占位符）。"""
    from app.core.startup_validator import StartupValidator

    if not api_key:
        return False
    return StartupValidator()._is_valid_api_key(str(api_key))


def validate_llm_provider_config(config: dict) -> None:
    """
    校验 LLM 配置中的 API Key 是否可用。
    在任务提交前调用，避免运行到一半才 401。
    """
    checks = (
        ("快速", "quick_think_llm", "quick_provider", "quick_api_key"),
        ("深度", "deep_think_llm", "deep_provider", "deep_api_key"),
    )
    issues: list[str] = []

    for role_label, model_key, provider_key, api_key_key in checks:
        model = config.get(model_key) or "未知模型"
        provider = config.get(provider_key) or config.get("llm_provider") or "未知供应商"
        api_key = config.get(api_key_key)
        if not is_valid_api_key(api_key):
            issues.append(f"{role_label}模型「{model}」({provider}) 未配置有效 API Key")

    if issues:
        raise ValueError(
            "；".join(issues)
            + "。请在「配置管理 → 大模型配置」填写对应厂家/模型的密钥，或配置 .env 后重启服务。"
        )
