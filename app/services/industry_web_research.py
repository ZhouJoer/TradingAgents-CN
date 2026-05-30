"""Authoritative web research providers for industry analysis."""

from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


AUTHORITY_DOMAINS = (
    "gov.cn",
    "ndrc.gov.cn",
    "miit.gov.cn",
    "stats.gov.cn",
    "mof.gov.cn",
    "pbc.gov.cn",
    "csrc.gov.cn",
    "sse.com.cn",
    "szse.cn",
    "bse.cn",
    "cninfo.com.cn",
    "cdb.com.cn",
    "sac.net.cn",
    "eastmoney.com",
    "dfcfw.com",
    "10jqka.com.cn",
)


@dataclass
class SearchResult:
    title: str
    url: str
    source: str = ""
    domain: str = ""
    published_at: Optional[str] = None
    snippet: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "domain": self.domain,
            "published_at": self.published_at,
            "snippet": self.snippet,
        }


class IndustryWebResearchProvider(ABC):
    @abstractmethod
    async def search(self, queries: List[str], max_results: int) -> List[SearchResult]:
        """Search authoritative web sources."""


def _is_valid_api_key(value: Optional[str]) -> bool:
    if not value:
        return False
    value = value.strip().strip('"').strip("'")
    if not value:
        return False
    if value.startswith(("your_", "your-")) or value.endswith(("_here", "-here")):
        return False
    return len(value) > 10


def _domain_from_url(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _is_allowed_domain(domain: str, allowlist: Iterable[str] = AUTHORITY_DOMAINS) -> bool:
    domain = (domain or "").lower().removeprefix("www.")
    return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in allowlist)


class BochaWebResearchProvider(IndustryWebResearchProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("BOCHA_API_KEY") or settings.BOCHA_API_KEY
        self.base_url = base_url or settings.BOCHA_API_BASE_URL
        self.timeout = timeout or settings.INDUSTRY_WEB_SEARCH_TIMEOUT

    @property
    def available(self) -> bool:
        return _is_valid_api_key(self.api_key)

    async def search(self, queries: List[str], max_results: int) -> List[SearchResult]:
        if not self.available:
            logger.info("BOCHA_API_KEY is not configured; skip industry web search")
            return []

        results: List[SearchResult] = []
        per_query = max(3, min(8, max_results))
        for query in queries:
            if len(results) >= max_results:
                break
            try:
                items = await asyncio.to_thread(self._search_once, query, per_query)
                results.extend(items)
            except Exception as exc:
                logger.warning("Bocha search failed for query=%s: %s", query, exc)

        return _dedupe_and_filter(results, max_results)

    def _search_once(self, query: str, count: int) -> List[SearchResult]:
        payload = {
            "query": query,
            "count": count,
            "summary": True,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(
            self.base_url,
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return self._parse_response(data)

    def _parse_response(self, data: Dict[str, Any]) -> List[SearchResult]:
        raw_items: Any = None
        if isinstance(data.get("data"), dict):
            data_section = data["data"]
            web_pages = data_section.get("webPages") or data_section.get("webpages")
            if isinstance(web_pages, dict):
                raw_items = web_pages.get("value")
            raw_items = raw_items or data_section.get("results") or data_section.get("items")
        raw_items = raw_items or data.get("results") or data.get("items") or []

        results: List[SearchResult] = []
        if not isinstance(raw_items, list):
            return results

        for item in raw_items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or item.get("link") or "").strip()
            domain = _domain_from_url(url)
            if not url or not _is_allowed_domain(domain):
                continue
            title = str(item.get("name") or item.get("title") or "").strip()
            snippet = str(
                item.get("snippet")
                or item.get("summary")
                or item.get("description")
                or ""
            ).strip()
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    source=str(item.get("siteName") or item.get("source") or domain),
                    domain=domain,
                    published_at=item.get("datePublished") or item.get("published_at") or item.get("date"),
                    snippet=snippet,
                )
            )
        return results


class NullIndustryWebResearchProvider(IndustryWebResearchProvider):
    async def search(self, queries: List[str], max_results: int) -> List[SearchResult]:
        return []


def build_authority_queries(keywords: List[str], domains: Iterable[str] = AUTHORITY_DOMAINS) -> List[str]:
    queries: List[str] = []
    for keyword in keywords:
        clean = keyword.strip()
        if not clean:
            continue
        for domain in domains:
            queries.append(f'{clean} 行业 政策 报告 site:{domain}')
    return queries


def _dedupe_and_filter(results: List[SearchResult], limit: int) -> List[SearchResult]:
    seen = set()
    deduped: List[SearchResult] = []
    for result in results:
        domain = result.domain or _domain_from_url(result.url)
        if not _is_allowed_domain(domain):
            continue
        key = result.url.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.domain = domain
        deduped.append(result)
        if len(deduped) >= limit:
            break
    return deduped


def get_industry_web_research_provider() -> IndustryWebResearchProvider:
    provider = (settings.INDUSTRY_WEB_SEARCH_PROVIDER or "bocha").lower()
    if not settings.INDUSTRY_WEB_SEARCH_ENABLED:
        return NullIndustryWebResearchProvider()
    if provider == "bocha":
        return BochaWebResearchProvider()
    logger.warning("Unsupported industry web search provider: %s", provider)
    return NullIndustryWebResearchProvider()
