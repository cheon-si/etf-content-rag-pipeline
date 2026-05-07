"""clients/ 단위 테스트 — Mock API."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from llm_pipeline.clients.anthropic_client import AnthropicClient, _extract_and_parse
from llm_pipeline.clients.gemini_client import GeminiClient
from llm_pipeline.schemas import IntentOutput, TokenUsage


# ── 공통 픽스처 ───────────────────────────────────────────────────────────────

VALID_INTENT_JSON = json.dumps({
    "intent_type": "Informational",
    "confidence": 0.85,
    "reasoning": "투자자들이 ETF 기초 정보를 찾고 있습니다.",
})


def _mock_anthropic_response(text: str, input_tokens: int = 100, output_tokens: int = 200):
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    content = MagicMock()
    content.text = text
    response = MagicMock()
    response.content = [content]
    response.usage = usage
    return response


def _mock_gemini_response(text: str, prompt_tokens: int = 100, candidate_tokens: int = 200):
    meta = MagicMock()
    meta.prompt_token_count = prompt_tokens
    meta.candidates_token_count = candidate_tokens
    response = MagicMock()
    response.text = text
    response.usage_metadata = meta
    return response


# ── AnthropicClient ───────────────────────────────────────────────────────────

class TestAnthropicClient:
    def test_returns_text_without_schema(self):
        with patch("anthropic.Anthropic") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.messages.create.return_value = _mock_anthropic_response("hello")

            client = AnthropicClient(api_key="test-key")
            result, usage = client.complete(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "test"}],
                stage="test",
            )

        assert result == "hello"
        assert isinstance(usage, TokenUsage)
        assert usage.input_tokens == 100
        assert usage.output_tokens == 200

    def test_parses_schema_from_json_response(self):
        with patch("anthropic.Anthropic") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.messages.create.return_value = _mock_anthropic_response(VALID_INTENT_JSON)

            client = AnthropicClient(api_key="test-key")
            result, usage = client.complete(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "test"}],
                stage="s1",
                response_schema=IntentOutput,
            )

        assert isinstance(result, IntentOutput)
        assert result.intent_type == "Informational"
        assert result.confidence == pytest.approx(0.85)

    def test_parses_schema_from_fenced_code_block(self):
        fenced = f"```json\n{VALID_INTENT_JSON}\n```"
        with patch("anthropic.Anthropic") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.messages.create.return_value = _mock_anthropic_response(fenced)

            client = AnthropicClient(api_key="test-key")
            result, _ = client.complete(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "test"}],
                stage="s1",
                response_schema=IntentOutput,
            )

        assert isinstance(result, IntentOutput)

    def test_cost_calculated(self):
        with patch("anthropic.Anthropic") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.messages.create.return_value = _mock_anthropic_response(
                "x", input_tokens=1_000_000, output_tokens=1_000_000
            )

            client = AnthropicClient(api_key="test-key")
            _, usage = client.complete(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "test"}],
                stage="test",
            )

        # claude-sonnet-4-6: $3 input + $15 output = $18 per 1M each
        assert usage.cost_usd == pytest.approx(18.0)

    def test_retries_on_rate_limit(self):
        import anthropic as _anthropic

        with patch("anthropic.Anthropic") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.messages.create.side_effect = [
                _anthropic.RateLimitError("rate limit", response=MagicMock(), body={}),
                _mock_anthropic_response("ok"),
            ]

            with patch("time.sleep"):
                client = AnthropicClient(api_key="test-key")
                result, _ = client.complete(
                    model="claude-sonnet-4-6",
                    messages=[{"role": "user", "content": "test"}],
                    stage="test",
                )

        assert result == "ok"

    def test_raises_after_max_retries(self):
        import anthropic as _anthropic

        with patch("anthropic.Anthropic") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.messages.create.side_effect = _anthropic.RateLimitError(
                "rate limit", response=MagicMock(), body={}
            )

            with patch("time.sleep"):
                client = AnthropicClient(api_key="test-key")
                with pytest.raises(RuntimeError, match="재시도 후 실패"):
                    client.complete(
                        model="claude-sonnet-4-6",
                        messages=[{"role": "user", "content": "test"}],
                        stage="test",
                    )


# ── GeminiClient ──────────────────────────────────────────────────────────────

class TestGeminiClient:
    def _make_client_with_mock(self, mock_response):
        """GeminiClient를 생성하고 generate_content를 mock으로 교체한다."""
        with patch("google.genai.Client") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.models.generate_content.return_value = mock_response
            client = GeminiClient.__new__(GeminiClient)
            client._model_name = "gemini-2.5-pro"
            client._client = mock_instance
        return client, mock_instance

    def test_returns_text_without_schema(self):
        mock_resp = _mock_gemini_response("gemini reply")
        with patch("google.genai.Client") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.models.generate_content.return_value = mock_resp
            client = GeminiClient.__new__(GeminiClient)
            client._model_name = "gemini-2.5-pro"
            client._client = mock_instance

            result, usage = client.complete(prompt="test", stage="test")

        assert result == "gemini reply"
        assert isinstance(usage, TokenUsage)

    def test_parses_schema_from_response(self):
        mock_resp = _mock_gemini_response(VALID_INTENT_JSON)
        with patch("google.genai.Client") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.models.generate_content.return_value = mock_resp
            client = GeminiClient.__new__(GeminiClient)
            client._model_name = "gemini-2.5-pro"
            client._client = mock_instance

            result, _ = client.complete(
                prompt="test", stage="s1", response_schema=IntentOutput
            )

        assert isinstance(result, IntentOutput)

    def test_cost_calculated(self):
        mock_resp = _mock_gemini_response("x", prompt_tokens=1_000_000, candidate_tokens=1_000_000)
        with patch("google.genai.Client") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.models.generate_content.return_value = mock_resp
            client = GeminiClient.__new__(GeminiClient)
            client._model_name = "gemini-2.5-flash"
            client._client = mock_instance

            _, usage = client.complete(prompt="test", stage="test")

        # gemini-2.5-flash: $0.075 input + $0.30 output = $0.375 per 1M each
        assert usage.cost_usd == pytest.approx(0.375)

    def test_retries_on_error(self):
        mock_instance = MagicMock()
        mock_instance.models.generate_content.side_effect = [
            Exception("transient error"),
            _mock_gemini_response("ok after retry"),
        ]
        client = GeminiClient.__new__(GeminiClient)
        client._model_name = "gemini-2.5-pro"
        client._client = mock_instance

        with patch("time.sleep"):
            result, _ = client.complete(prompt="test", stage="test")

        assert result == "ok after retry"


# ── AnthropicClient.complete_with_fallback ────────────────────────────────────

class TestCompleteWithFallback:
    def test_uses_opus_first(self):
        from llm_pipeline.config import ANTHROPIC_OPUS
        with patch("anthropic.Anthropic") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.messages.create.return_value = _mock_anthropic_response("ok")

            client = AnthropicClient(api_key="test-key")
            client.complete_with_fallback(
                messages=[{"role": "user", "content": "test"}],
                stage="test",
            )

        call_kwargs = mock_instance.messages.create.call_args.kwargs
        assert call_kwargs["model"] == ANTHROPIC_OPUS

    def test_fallback_to_sonnet_on_opus_failure(self):
        import anthropic as _anthropic
        from llm_pipeline.config import ANTHROPIC_SONNET

        with patch("anthropic.Anthropic") as mock_cls:
            mock_instance = mock_cls.return_value
            mock_instance.messages.create.side_effect = [
                _anthropic.RateLimitError("rate limit", response=MagicMock(), body={}),
                _anthropic.RateLimitError("rate limit", response=MagicMock(), body={}),
                _anthropic.RateLimitError("rate limit", response=MagicMock(), body={}),
                _mock_anthropic_response("fallback ok"),
            ]

            with patch("time.sleep"):
                client = AnthropicClient(api_key="test-key")
                result, _ = client.complete_with_fallback(
                    messages=[{"role": "user", "content": "test"}],
                    stage="test",
                )

        assert result == "fallback ok"
        last_call = mock_instance.messages.create.call_args
        assert last_call.kwargs["model"] == ANTHROPIC_SONNET


# ── _extract_and_parse ────────────────────────────────────────────────────────

class TestExtractAndParse:
    def test_plain_json(self):
        result = _extract_and_parse(VALID_INTENT_JSON, IntentOutput)
        assert result.intent_type == "Informational"

    def test_fenced_json_block(self):
        text = f"```json\n{VALID_INTENT_JSON}\n```"
        result = _extract_and_parse(text, IntentOutput)
        assert result.confidence == pytest.approx(0.85)

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            _extract_and_parse("not json at all", IntentOutput)
