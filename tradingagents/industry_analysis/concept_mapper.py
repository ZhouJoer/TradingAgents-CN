from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import re
from difflib import SequenceMatcher, get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from tradingagents.utils.structured_output import extract_json_text

try:
    from tradingagents.utils.logging_manager import get_logger
except Exception:
    import logging

    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
else:
    BaseChatModel = Any

logger = get_logger("industry_analysis")

try:
    from app.models.industry_analysis import ConceptMappingResult
except Exception:
    industry_analysis_model_path = Path(__file__).resolve().parents[2] / "app" / "models" / "industry_analysis.py"
    spec = importlib.util.spec_from_file_location("industry_analysis_model_fallback", industry_analysis_model_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load ConceptMappingResult from {industry_analysis_model_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ConceptMappingResult = module.ConceptMappingResult

_GENERIC_SUFFIXES = ("相关", "概念", "板块", "行业", "主题", "赛道")


@lru_cache(maxsize=1)
def _get_cached_board_names() -> tuple[tuple[str, ...], tuple[str, ...]]:
    import akshare as ak

    concept_df = ak.stock_board_concept_name_em()
    industry_df = ak.stock_board_industry_name_em()

    concept_names = _extract_board_names(concept_df)
    industry_names = _extract_board_names(industry_df)
    return tuple(concept_names), tuple(industry_names)


def _extract_board_names(dataframe: Any) -> list[str]:
    if dataframe is None or getattr(dataframe, "empty", True):
        return []

    preferred_columns = ("板块名称", "名称", "概念名称", "行业名称", "name")
    column_name = next((col for col in preferred_columns if col in dataframe.columns), dataframe.columns[0])
    values = dataframe[column_name].tolist()
    return sorted({str(value).strip() for value in values if str(value).strip() and str(value).strip().lower() != "nan"})


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (dict, bytes)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _extract_keywords(user_concept: str) -> list[str]:
    """从用户概念中提取关键词（纯文本处理，不使用硬编码映射）"""
    raw = (user_concept or "").strip()
    if not raw:
        return []

    candidates = [raw]
    parts = re.split(r"[、，,；;\s/]+", raw)
    candidates.extend(part.strip() for part in parts if part.strip())

    for part in list(candidates):
        simplified = part
        for suffix in _GENERIC_SUFFIXES:
            simplified = simplified.removesuffix(suffix)
        simplified = simplified.strip()
        if simplified and simplified != part:
            candidates.append(simplified)

    return _dedupe_preserve_order(candidates)


def _extract_json_text(text: str) -> str:
    return extract_json_text(text)


def _parse_llm_json(text: str) -> dict[str, Any]:
    json_text = _extract_json_text(text)
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        pass

    # 尝试修复常见的 JSON 格式问题
    # 1. 尝试补全截断的字符串（添加缺失的引号和括号）
    fixed = json_text.rstrip()
    if fixed.count('"') % 2 == 1:
        fixed += '"'
    # 补全缺失的中括号和大括号
    open_brackets = fixed.count('[') - fixed.count(']')
    open_braces = fixed.count('{') - fixed.count('}')
    fixed += ']' * max(0, open_brackets)
    fixed += '}' * max(0, open_braces)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 2. 尝试 ast.literal_eval
    try:
        parsed = ast.literal_eval(json_text)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, SyntaxError):
        pass

    # 3. 尝试用正则提取关键字段
    result: dict[str, Any] = {}
    for key in ("board_concepts", "board_industries", "keywords"):
        match = re.search(rf'"{key}"\s*:\s*\[(.*?)\]', json_text, re.DOTALL)
        if match:
            items = re.findall(r'"([^"]+)"', match.group(1))
            result[key] = items
    reasoning_match = re.search(r'"reasoning"\s*:\s*"([^"]*)', json_text)
    if reasoning_match:
        result["reasoning"] = reasoning_match.group(1)
    if result:
        return result

    raise ValueError("LLM response is not a valid JSON object")


class ConceptMapper:
    def __init__(self, llm: BaseChatModel):
        self.llm = llm

    async def map_concept(self, user_concept: str) -> ConceptMappingResult:
        normalized_concept = (user_concept or "").strip()
        if not normalized_concept:
            return ConceptMappingResult(
                user_concept="",
                board_concepts=[],
                board_industries=[],
                keywords=[],
                reasoning="用户概念为空，无法进行映射。",
            )

        try:
            concept_boards, industry_boards = await asyncio.to_thread(_get_cached_board_names)
        except Exception as exc:
            logger.warning("获取 AKShare 板块名称失败，将使用LLM直接推断板块: %s", exc)
            # AKShare 不可用时，让 LLM 自由推断板块名称（不做校验）
            return await self._map_without_board_list(normalized_concept)

        try:
            mapping = await self._map_with_llm(
                user_concept=normalized_concept,
                available_concepts=list(concept_boards),
                available_industries=list(industry_boards),
            )
            if mapping.board_concepts or mapping.board_industries:
                return mapping
            logger.warning("LLM 未返回有效板块映射，使用模糊匹配兜底: %s", normalized_concept)
        except Exception as exc:
            logger.exception("LLM 概念映射失败: %s", exc)

        return self._fallback_match(
            user_concept=normalized_concept,
            available_concepts=list(concept_boards),
            available_industries=list(industry_boards),
            reason="LLM 映射失败或未命中有效板块，已使用模糊匹配兜底。",
        )

    async def _map_with_llm(
        self,
        user_concept: str,
        available_concepts: Sequence[str],
        available_industries: Sequence[str],
    ) -> ConceptMappingResult:
        if self.llm is None:
            raise ValueError("LLM instance is required")

        prompt = self._build_prompt(user_concept, available_concepts, available_industries)

        if hasattr(self.llm, "ainvoke"):
            try:
                response = await self.llm.ainvoke(prompt)
            except Exception:
                if not hasattr(self.llm, "invoke"):
                    raise
                response = await asyncio.to_thread(self.llm.invoke, prompt)
        elif hasattr(self.llm, "invoke"):
            response = await asyncio.to_thread(self.llm.invoke, prompt)
        else:
            raise TypeError("LLM instance must provide ainvoke or invoke")

        response_text = self._response_to_text(response)
        payload = _parse_llm_json(response_text)

        keywords = _dedupe_preserve_order(
            [user_concept, *_extract_keywords(user_concept), *_coerce_string_list(payload.get("keywords"))]
        )[:8]
        board_concepts = self._normalize_board_selection(
            _coerce_string_list(payload.get("board_concepts")), available_concepts, 5
        )
        board_industries = self._normalize_board_selection(
            _coerce_string_list(payload.get("board_industries")), available_industries, 3
        )

        reasoning = str(payload.get("reasoning") or "").strip() or "模型完成了概念映射。"
        return ConceptMappingResult(
            user_concept=user_concept,
            board_concepts=board_concepts,
            board_industries=board_industries,
            keywords=keywords,
            reasoning=reasoning,
        )

    async def _map_without_board_list(self, user_concept: str) -> ConceptMappingResult:
        """当 AKShare 板块列表不可用时，让 LLM 自由推断东方财富板块名称"""
        prompt = f"""
你是A股板块映射助手。需要把用户的模糊概念映射为东方财富（AKShare）可查询的概念板块和行业板块名称。
注意：当前无法获取实时板块列表，请根据你的知识直接给出最可能的板块名称。

用户概念：{user_concept}

要求：
1. board_concepts: 给出最可能匹配的东方财富概念板块名称，最多5个。名称要尽量精确（如"人工智能"而非"AI"）。
2. board_industries: 给出相关的东方财富行业板块名称，最多3个。
3. keywords: 3-8个搜索关键词。
4. reasoning: 简要说明选择原因。
5. 只输出合法JSON，不要输出Markdown或代码块。

返回JSON：
{{
  "user_concept": "{user_concept}",
  "board_concepts": ["概念板块1", "概念板块2"],
  "board_industries": ["行业板块1"],
  "keywords": ["关键词1", "关键词2"],
  "reasoning": "说明原因"
}}
""".strip()

        try:
            if hasattr(self.llm, "ainvoke"):
                try:
                    response = await self.llm.ainvoke(prompt)
                except Exception:
                    if not hasattr(self.llm, "invoke"):
                        raise
                    response = await asyncio.to_thread(self.llm.invoke, prompt)
            elif hasattr(self.llm, "invoke"):
                response = await asyncio.to_thread(self.llm.invoke, prompt)
            else:
                raise TypeError("LLM instance must provide ainvoke or invoke")

            response_text = self._response_to_text(response)
            payload = _parse_llm_json(response_text)

            keywords = _dedupe_preserve_order(
                [user_concept, *_extract_keywords(user_concept), *_coerce_string_list(payload.get("keywords"))]
            )[:8]
            # 不校验板块名（因为没有列表），直接使用 LLM 返回的名称
            board_concepts = _coerce_string_list(payload.get("board_concepts"))[:5]
            board_industries = _coerce_string_list(payload.get("board_industries"))[:3]
            reasoning = str(payload.get("reasoning") or "").strip() or "LLM直接推断板块映射（AKShare板块列表不可用）。"

            if board_concepts or board_industries:
                return ConceptMappingResult(
                    user_concept=user_concept,
                    board_concepts=board_concepts,
                    board_industries=board_industries,
                    keywords=keywords,
                    reasoning=reasoning,
                )
        except Exception as exc:
            logger.warning("LLM自由推断板块映射失败: %s", exc)

        # LLM也失败了，用关键词扩展兜底
        keywords = _extract_keywords(user_concept)
        return ConceptMappingResult(
            user_concept=user_concept,
            board_concepts=keywords[:5],
            board_industries=[],
            keywords=keywords,
            reasoning="AKShare板块列表和LLM均不可用，使用关键词扩展作为板块候选。",
        )

    def _build_prompt(
        self,
        user_concept: str,
        available_concepts: Sequence[str],
        available_industries: Sequence[str],
    ) -> str:
        return f"""
你是A股板块映射助手，需要把用户的模糊概念映射为 AKShare 可直接查询的东方财富概念板块和行业板块名称。

用户概念：{user_concept}

可选概念板块列表（只能从这里选）：
{json.dumps(list(available_concepts), ensure_ascii=False)}

可选行业板块列表（只能从这里选）：
{json.dumps(list(available_industries), ensure_ascii=False)}

请严格遵守：
1. board_concepts 只能填写上面概念板块列表中的名称，最多 5 个。
2. board_industries 只能填写上面行业板块列表中的名称，最多 3 个。
3. keywords 输出 3-8 个相关搜索关键词，优先保留用户原始概念及其核心词。
4. reasoning 用中文简要解释为什么这些板块相关；如果概念很宽泛，优先选最具代表性的板块。
5. 如果没有合适候选，可以返回空数组。
6. 只输出合法 JSON，不要输出 Markdown，不要输出代码块。

返回 JSON 结构必须为：
{{
  "user_concept": "{user_concept}",
  "board_concepts": ["概念板块1", "概念板块2"],
  "board_industries": ["行业板块1"],
  "keywords": ["关键词1", "关键词2"],
  "reasoning": "说明原因"
}}
""".strip()

    def _normalize_board_selection(
        self,
        candidates: Sequence[str],
        available_boards: Sequence[str],
        limit: int,
    ) -> list[str]:
        normalized_lookup = {_normalize_text(board): board for board in available_boards}
        results: list[str] = []

        for candidate in candidates:
            if len(results) >= limit:
                break
            board = str(candidate).strip()
            if not board:
                continue

            exact = normalized_lookup.get(_normalize_text(board))
            if exact:
                if exact not in results:
                    results.append(exact)
                continue

            compact_candidate = _normalize_text(board)
            contains_matches = [
                name for name in available_boards if compact_candidate and compact_candidate in _normalize_text(name)
            ]
            if contains_matches:
                selected = min(contains_matches, key=len)
                if selected not in results:
                    results.append(selected)
                continue

            close_matches = get_close_matches(
                compact_candidate,
                list(normalized_lookup.keys()),
                n=1,
                cutoff=0.55,
            )
            if close_matches:
                matched = normalized_lookup[close_matches[0]]
                if matched not in results:
                    results.append(matched)
                continue

            best_ratio = 0.0
            best_match = ""
            for board_name in available_boards:
                ratio = SequenceMatcher(None, compact_candidate, _normalize_text(board_name)).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = board_name
            if best_ratio >= 0.6 and best_match and best_match not in results:
                results.append(best_match)

        return results[:limit]

    def _response_to_text(self, response: Any) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return str(content)

    def _fallback_match(
        self,
        user_concept: str,
        available_concepts: Sequence[str],
        available_industries: Sequence[str],
        reason: str,
    ) -> ConceptMappingResult:
        keywords = _extract_keywords(user_concept)
        board_concepts = self._fuzzy_match(keywords, available_concepts, limit=5)
        board_industries = self._fuzzy_match(keywords, available_industries, limit=3)

        reasoning = reason
        if board_concepts or board_industries:
            reasoning = (
                f"{reason} 根据用户概念及关键词 {keywords} 对 AKShare 板块名称进行了模糊匹配。"
            )
        else:
            reasoning = f"{reason} 未找到明显匹配的概念或行业板块，建议细化关键词后重试。"

        return ConceptMappingResult(
            user_concept=user_concept,
            board_concepts=board_concepts,
            board_industries=board_industries,
            keywords=keywords,
            reasoning=reasoning,
        )

    def _fuzzy_match(self, keywords: Sequence[str], boards: Sequence[str], limit: int) -> list[str]:
        if not keywords or not boards:
            return []

        scored_matches: list[tuple[float, str]] = []
        for board in boards:
            normalized_board = _normalize_text(board)
            best_score = 0.0
            for keyword in keywords:
                normalized_keyword = _normalize_text(keyword)
                if not normalized_keyword:
                    continue
                if normalized_keyword in normalized_board or normalized_board in normalized_keyword:
                    best_score = max(best_score, 1.0)
                    continue
                ratio = SequenceMatcher(None, normalized_keyword, normalized_board).ratio()
                best_score = max(best_score, ratio)
            if best_score >= 0.45:
                scored_matches.append((best_score, board))

        scored_matches.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
        return _dedupe_preserve_order(board for _, board in scored_matches)[:limit]
