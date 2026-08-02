# SPDX-License-Identifier: Apache-2.0
"""LLM 서비스 — 프로바이더 싱글턴 관리."""

import logging
from collections.abc import AsyncIterator

from app.llm.provider import ChatProvider, create_chat_provider

logger = logging.getLogger(__name__)

_provider: ChatProvider | None = None


def get_chat_provider() -> ChatProvider:
    global _provider
    if _provider is None:
        _provider = create_chat_provider()
    return _provider


async def shutdown_chat_provider() -> None:
    global _provider
    if _provider is not None:
        await _provider.aclose()
        _provider = None


async def complete(messages: list[dict]) -> str:
    return await get_chat_provider().complete(messages)


async def complete_with_usage(
    messages: list[dict], *, overrides: dict | None = None
) -> tuple[str, dict]:
    return await get_chat_provider().complete_with_usage(messages, overrides=overrides)


def stream(messages: list[dict], *, overrides: dict | None = None) -> AsyncIterator[str]:
    return get_chat_provider().stream(messages, overrides=overrides)
