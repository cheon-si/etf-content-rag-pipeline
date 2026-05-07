"""LLM 클라이언트 공유 유틸리티 — 비용 계산·JSON 파싱·스키마 instruction."""
from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel

from llm_pipeline.config import PRICING

T = TypeVar("T", bound=BaseModel)


def calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICING.get(model, {"input": 0.0, "output": 0.0})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def build_schema_instruction(schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
    return (
        f"\n\n반드시 다음 JSON 스키마를 준수하는 JSON만 출력하세요. "
        f"설명 없이 JSON만 반환:\n{schema_json}"
    )


def extract_and_parse(text: str, schema: type[T]) -> T:
    """LLM 응답에서 JSON 블록을 추출하고 Pydantic 모델로 파싱한다.

    시도 순서:
    1. ```json ... ``` 코드 펜스 내 JSON
    2. 전체 텍스트를 JSON으로 직접 파싱
    3. 정규식으로 최외곽 { ... } 블록 추출
    """
    if "```" in text:
        start = text.find("```")
        end = text.rfind("```")
        block = text[start:end]
        lines = block.splitlines()
        json_str = "\n".join(lines[1:]) if lines else block
        try:
            return schema.model_validate_json(json_str)
        except Exception:
            pass

    try:
        return schema.model_validate_json(text.strip())
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return schema.model_validate_json(match.group())

    raise ValueError(
        f"JSON 파싱 실패 — 응답에서 유효한 JSON을 찾지 못했습니다.\n응답 앞부분:\n{text[:300]}"
    )
