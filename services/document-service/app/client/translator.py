import logging

import httpx
from fastapi import HTTPException

from ..config import GROUND_TIMEOUT, SUMMARY_TIMEOUT, TRANSLATOR_URL

logger = logging.getLogger(__name__)


async def _request_translator(path: str, payload: dict, key: str, timeout: float = GROUND_TIMEOUT):
    """The `key` field of the translator's JSON response."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{TRANSLATOR_URL}{path}", json=payload)
    except httpx.HTTPError as exc:
        logger.warning("%s: translator unreachable: %s", path, exc)
        raise HTTPException(502, "translator service unavailable") from exc
    if response.status_code != 200:
        logger.warning("%s: translator returned %d: %s", path, response.status_code, response.text[:500])
        raise HTTPException(502, f"translator service error ({response.status_code})")
    try:
        return response.json()[key]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "translator service returned an invalid response") from exc


async def _request_list(path: str, payload: dict, key: str) -> list[dict]:
    value = await _request_translator(path, payload, key)
    if not isinstance(value, list):
        raise HTTPException(502, "translator service returned an invalid response")
    return value


async def request_groundings(state: str, lines: list[str]) -> list[dict]:
    return await _request_list("/ground-state", {"state": state, "context": lines}, "groundings")


async def request_suggestions(instruction: str, lines: list[str]) -> list[dict]:
    """The instruction is the translator's `intent`."""
    return await _request_list("/giveme-suggestion", {"intent": instruction, "context": lines}, "suggestions")


async def request_summary(instruction: str, highlights: list[str]) -> str:
    """A short answer to the instruction from the highlighted text."""
    summary = await _request_translator(
        "/summarize-suggestion", {"intent": instruction, "highlights": highlights}, "summary", SUMMARY_TIMEOUT
    )
    if not isinstance(summary, str):
        raise HTTPException(502, "translator service returned an invalid response")
    return summary
