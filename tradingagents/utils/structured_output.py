"""Small helpers for extracting JSON blocks from LLM text responses."""

from __future__ import annotations

import json
import re
from typing import Any, Dict

STRUCTURED_PAYLOAD_KEYS = (
    "industry_logic_sections",
    "stock_selection_sections",
    "supply_chain_analysis",
    "recommendation_groups",
    "recommendations",
)

STRIP_PAYLOAD_KEYS = STRUCTURED_PAYLOAD_KEYS[:-1]


def loads_json_object(raw: str) -> Dict[str, Any]:
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def looks_like_structured_payload(payload: Dict[str, Any]) -> bool:
    return any(key in payload for key in STRUCTURED_PAYLOAD_KEYS)


def contains_structured_payload_keys(text: str) -> bool:
    return any(key in text for key in STRIP_PAYLOAD_KEYS)


def extract_json_text(text: str) -> str:
    """Return JSON text from a fenced block or the outermost object in a response."""
    cleaned = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned


def extract_structured_payload(text: str) -> Dict[str, Any]:
    """Extract the optional structured JSON payload from an LLM response."""
    for match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", text or "", re.DOTALL | re.IGNORECASE):
        payload = loads_json_object(match.group(1))
        if looks_like_structured_payload(payload):
            return payload

    marker_match = re.search(r"STRUCTURED_JSON\s*:\s*(\{.*\})", text or "", re.DOTALL | re.IGNORECASE)
    if marker_match:
        payload = loads_json_object(marker_match.group(1))
        if looks_like_structured_payload(payload):
            return payload

    return {}


def strip_structured_payload_blocks(text: str) -> str:
    """Remove machine-readable JSON blocks from user-facing Markdown."""
    if not text:
        return ""

    cleaned = text
    fenced_pattern = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
    for match in list(fenced_pattern.finditer(text)):
        payload_text = match.group(1)
        payload = loads_json_object(payload_text)
        if looks_like_structured_payload(payload) or contains_structured_payload_keys(payload_text):
            cleaned = cleaned.replace(match.group(0), "")

    marker_pattern = re.compile(r"\s*STRUCTURED_JSON\s*:\s*(\{.*\})\s*$", re.DOTALL | re.IGNORECASE)
    marker_match = marker_pattern.search(cleaned)
    if marker_match:
        payload_text = marker_match.group(1)
        payload = loads_json_object(payload_text)
        if looks_like_structured_payload(payload) or contains_structured_payload_keys(payload_text):
            cleaned = cleaned[:marker_match.start()]

    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()
