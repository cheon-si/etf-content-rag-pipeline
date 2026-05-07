"""Anthropic Messages API 래퍼 — 재시도·토큰 추적."""
from __future__ import annotations

import logging
import os
import time
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from llm_pipeline.config import ANTHROPIC_OPUS, ANTHROPIC_SONNET, MAX_RETRIES
from llm_pipeline.schemas import TokenUsage
from llm_pipeline.clients._shared import build_schema_instruction, calc_cost, extract_and_parse

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_RETRY_BASE_SECONDS = 1.0

# 하위 호환 — test_clients.py가 이 이름으로 import함
_extract_and_parse = extract_and_parse


class AnthropicClient:
    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ["ANTHROPIC_API_KEY"]
        )

    def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system: str = "",
        max_tokens: int = 4096,
        stage: str = "unknown",
        response_schema: type[T] | None = None,
    ) -> tuple[str | T, TokenUsage]:
        """Messages API 호출. response_schema 지정 시 Pydantic 모델로 파싱한다."""
        if response_schema is not None:
            system = system + build_schema_instruction(response_schema)

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                logger.info("[%s] %s 호출 시도 %d/%d", stage, model, attempt + 1, MAX_RETRIES)
                kwargs: dict[str, Any] = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": messages,
                }
                if system:
                    kwargs["system"] = system

                response = self._client.messages.create(**kwargs)
                raw_text = response.content[0].text
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                cost = calc_cost(model, input_tokens, output_tokens)

                usage = TokenUsage(
                    model=model,
                    stage=stage,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                )
                logger.info(
                    "[%s] %s 완료 — input=%d output=%d cost=$%.4f",
                    stage, model, input_tokens, output_tokens, cost,
                )

                if response_schema is not None:
                    return extract_and_parse(raw_text, response_schema), usage

                return raw_text, usage

            except (anthropic.RateLimitError, anthropic.APIStatusError) as exc:
                last_exc = exc
                wait = _RETRY_BASE_SECONDS * (2 ** attempt)
                logger.warning("[%s] API 오류 (%s) — %.1fs 후 재시도", stage, exc, wait)
                time.sleep(wait)
            except anthropic.APIConnectionError as exc:
                last_exc = exc
                wait = _RETRY_BASE_SECONDS * (2 ** attempt)
                logger.warning("[%s] 연결 오류 — %.1fs 후 재시도", stage, wait)
                time.sleep(wait)

        raise RuntimeError(
            f"[{stage}] {model} {MAX_RETRIES}회 재시도 후 실패: {last_exc}"
        ) from last_exc

    def complete_with_fallback(
        self,
        messages: list[dict[str, Any]],
        stage: str,
        response_schema: type[T] | None = None,
        max_tokens: int = 4096,
        system: str = "",
    ) -> tuple[str | T, TokenUsage]:
        """Opus → Sonnet 폴백 패턴으로 complete한다."""
        try:
            return self.complete(
                model=ANTHROPIC_OPUS,
                messages=messages,
                stage=stage,
                response_schema=response_schema,
                max_tokens=max_tokens,
                system=system,
            )
        except RuntimeError:
            logger.warning("[%s] Opus 실패 — Sonnet 폴백", stage)
            return self.complete(
                model=ANTHROPIC_SONNET,
                messages=messages,
                stage=f"{stage}_fallback",
                response_schema=response_schema,
                max_tokens=max_tokens,
                system=system,
            )
