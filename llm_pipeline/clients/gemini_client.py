"""Google AI Studio (Gemini) API 래퍼 — 재시도·Search grounding·토큰 추적."""
from __future__ import annotations

import logging
import os
import time
from typing import TypeVar

from pydantic import BaseModel

from llm_pipeline.config import MAX_RETRIES
from llm_pipeline.schemas import TokenUsage
from llm_pipeline.clients._shared import build_schema_instruction, calc_cost, extract_and_parse

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_RETRY_BASE_SECONDS = 1.0


class GeminiClient:
    def __init__(self, api_key: str | None = None, model_name: str | None = None) -> None:
        from google import genai
        from llm_pipeline.config import GEMINI_PRO

        self._model_name = model_name or GEMINI_PRO
        self._client = genai.Client(api_key=api_key or os.environ["GOOGLE_API_KEY"])

    def complete(
        self,
        prompt: str,
        use_search_grounding: bool = False,
        stage: str = "unknown",
        response_schema: type[T] | None = None,
    ) -> tuple[str | T, TokenUsage]:
        """Gemini API 호출. use_search_grounding=True 시 Google Search grounding 활성화."""
        from google.genai import types

        if response_schema is not None:
            prompt = prompt + build_schema_instruction(response_schema)

        config_kwargs: dict = {}
        if use_search_grounding:
            config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(
                    "[%s] %s 호출 시도 %d/%d (grounding=%s)",
                    stage, self._model_name, attempt + 1, MAX_RETRIES, use_search_grounding,
                )
                generate_kwargs: dict = {
                    "model": self._model_name,
                    "contents": prompt,
                }
                if config is not None:
                    generate_kwargs["config"] = config

                response = self._client.models.generate_content(**generate_kwargs)
                raw_text = response.text or ""

                meta = getattr(response, "usage_metadata", None)
                input_tokens = getattr(meta, "prompt_token_count", 0) or 0
                output_tokens = getattr(meta, "candidates_token_count", 0) or 0
                cost = calc_cost(self._model_name, input_tokens, output_tokens)

                usage = TokenUsage(
                    model=self._model_name,
                    stage=stage,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                )
                logger.info(
                    "[%s] %s 완료 — input=%d output=%d cost=$%.4f",
                    stage, self._model_name, input_tokens, output_tokens, cost,
                )

                if response_schema is not None:
                    return extract_and_parse(raw_text, response_schema), usage

                return raw_text, usage

            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait = _RETRY_BASE_SECONDS * (2 ** attempt)
                logger.warning("[%s] Gemini 오류 (%s) — %.1fs 후 재시도", stage, exc, wait)
                time.sleep(wait)

        raise RuntimeError(
            f"[{stage}] {self._model_name} {MAX_RETRIES}회 재시도 후 실패: {last_exc}"
        ) from last_exc
