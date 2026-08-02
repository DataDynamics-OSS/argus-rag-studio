# SPDX-License-Identifier: Apache-2.0
"""생성 LLM 프로바이더 추상화.

- ``OpenAICompatibleChatProvider``: ``POST {server_url}/chat/completions`` (사내 서버 / vLLM /
  Ollama / OpenAI). OpenAI 호환이므로 httpx 로 직접 호출한다(임베딩과 동일 패턴).
- ``AnthropicProvider``: Anthropic Claude. **공식 ``anthropic`` SDK** 를 사용한다(httpx 직접
  호출 금지). 기본 모델 ``claude-opus-4-8``. opus 4.x 는 ``temperature``/``budget_tokens`` 를
  받지 않으므로 전송하지 않는다.

메시지 형식: ``[{"role": "system"|"user"|"assistant", "content": str}, ...]``.
Anthropic 은 system 을 top-level 인자로 분리하고 user/assistant 만 messages 로 보낸다.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from app.core.config import settings
from app.core.http import auth_headers

logger = logging.getLogger(__name__)


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """messages 에서 system 내용을 추출하고 나머지(user/assistant)를 반환한다."""
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    return "\n\n".join(system_parts), rest


class ChatProvider(ABC):
    """채팅 생성 프로바이더 인터페이스."""

    @abstractmethod
    async def complete(self, messages: list[dict]) -> str:
        ...

    @abstractmethod
    def stream(self, messages: list[dict], *, overrides: dict | None = None) -> AsyncIterator[str]:
        ...

    async def complete_with_usage(
        self, messages: list[dict], *, overrides: dict | None = None
    ) -> tuple[str, dict]:
        """답변 + 토큰 사용량({prompt_tokens, completion_tokens})을 함께 반환한다(관측용).

        ``overrides`` 로 model/max_tokens/temperature 를 호출 단위로 덮어쓸 수 있다(파이프라인).
        기본 구현은 토큰 정보를 모르므로 빈 dict 를 돌려준다. 프로바이더가 오버라이드한다.
        """
        return await self.complete(messages), {"prompt_tokens": None, "completion_tokens": None}

    async def aclose(self) -> None:
        return


class OpenAICompatibleChatProvider(ChatProvider):
    """OpenAI 호환 ``/chat/completions`` 클라이언트."""

    def __init__(self) -> None:
        base = settings.llm_server_url.rstrip("/")
        # 엔드포인트 URL 규약은 기반 환경 프로파일에 위임(기본은 {base}/chat/completions).
        from app.platform.factory import get_platform_profile
        self._url = get_platform_profile().llm_endpoint_url(base)
        self._model = settings.llm_model or "default"
        headers = {"Content-Type": "application/json"}
        headers.update(auth_headers(
            settings.llm_api_key, settings.llm_auth_header, settings.llm_auth_scheme
        ))
        self._client = httpx.AsyncClient(timeout=settings.llm_timeout, headers=headers)

    def _payload(self, messages: list[dict], stream: bool, overrides: dict | None) -> dict:
        o = overrides or {}
        return {
            "model": o.get("model") or self._model,
            "messages": messages,
            "max_tokens": o.get("max_tokens") or settings.llm_max_tokens,
            "temperature": o.get("temperature") if o.get("temperature") is not None else settings.llm_temperature,
            "stream": stream,
        }

    async def complete(self, messages: list[dict]) -> str:
        text, _ = await self.complete_with_usage(messages)
        return text

    async def complete_with_usage(
        self, messages: list[dict], *, overrides: dict | None = None
    ) -> tuple[str, dict]:
        resp = await self._client.post(self._url, json=self._payload(messages, False, overrides))
        if resp.status_code != 200:
            raise RuntimeError(f"LLM 서버 오류({resp.status_code}): {resp.text[:200]} @ {self._url}")
        data = resp.json()
        usage = data.get("usage") or {}
        return data["choices"][0]["message"]["content"], {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }

    async def stream(self, messages: list[dict], *, overrides: dict | None = None) -> AsyncIterator[str]:
        import json as _json

        async with self._client.stream(
            "POST", self._url, json=self._payload(messages, True, overrides)
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise RuntimeError(f"LLM 서버 오류({resp.status_code}): {body[:200]!r}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if chunk == "[DONE]":
                    break
                try:
                    delta = _json.loads(chunk)["choices"][0]["delta"].get("content")
                except Exception:
                    continue
                if delta:
                    yield delta

    async def aclose(self) -> None:
        await self._client.aclose()


class AnthropicProvider(ChatProvider):
    """Anthropic Claude 프로바이더 — 공식 ``anthropic`` SDK 사용."""

    def __init__(self) -> None:
        from anthropic import AsyncAnthropic

        api_key = settings.llm_api_key or None  # None 이면 ANTHROPIC_API_KEY 환경변수 사용
        self._client = AsyncAnthropic(api_key=api_key, timeout=settings.llm_timeout)
        self._model = settings.llm_model or "claude-opus-4-8"
        self._max_tokens = settings.llm_max_tokens

    async def complete(self, messages: list[dict]) -> str:
        text, _ = await self.complete_with_usage(messages)
        return text

    async def complete_with_usage(
        self, messages: list[dict], *, overrides: dict | None = None
    ) -> tuple[str, dict]:
        o = overrides or {}
        system, msgs = _split_system(messages)
        resp = await self._client.messages.create(
            model=o.get("model") or self._model,
            max_tokens=o.get("max_tokens") or self._max_tokens,
            system=system or None,
            messages=msgs,
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        u = getattr(resp, "usage", None)
        return text, {
            "prompt_tokens": getattr(u, "input_tokens", None),
            "completion_tokens": getattr(u, "output_tokens", None),
        }

    async def stream(self, messages: list[dict], *, overrides: dict | None = None) -> AsyncIterator[str]:
        o = overrides or {}
        system, msgs = _split_system(messages)
        async with self._client.messages.stream(
            model=o.get("model") or self._model,
            max_tokens=o.get("max_tokens") or self._max_tokens,
            system=system or None,
            messages=msgs,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def aclose(self) -> None:
        await self._client.close()


def create_chat_provider() -> ChatProvider:
    kind = settings.llm_provider.lower()
    if kind == "anthropic":
        logger.info("LLM 프로바이더: anthropic (model=%s)", settings.llm_model or "claude-opus-4-8")
        return AnthropicProvider()
    logger.info(
        "LLM 프로바이더: openai_compatible (%s, model=%s)",
        settings.llm_server_url, settings.llm_model or "default",
    )
    return OpenAICompatibleChatProvider()
