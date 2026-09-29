from __future__ import annotations

import pytest

from app.config import Settings
from app.llm.base import LLMError
from app.llm.openai_provider import OpenAICompatibleProvider, _extract_json_object


def _settings(*, retries: int = 2) -> Settings:
    return Settings(
        llm_provider="openai",
        llm_api_key="test-key",
        llm_model="test-model",
        llm_max_retries=retries,
    )


class _SequenceProvider(OpenAICompatibleProvider):
    def __init__(self, responses: list[dict], *, retries: int = 2) -> None:
        super().__init__(_settings(retries=retries))
        self.responses = iter(responses)
        self.payloads: list[dict] = []

    def _post_with_retry(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return next(self.responses)


def _raw(content: str, *, prompt_tokens: int = 2, completion_tokens: int = 3) -> dict:
    return {
        "model": "test-model",
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }


def test_extract_json_object_accepts_fence_and_surrounding_text() -> None:
    assert _extract_json_object('```json\n{"ok": true}\n```') == {"ok": True}
    assert _extract_json_object('结果如下：{"ok": true}，请查收') == {"ok": True}


def test_complete_json_reasks_model_after_malformed_json() -> None:
    provider = _SequenceProvider(
        [_raw('{"directions": [{"title": "算法工程师" "score": 88}]}'), _raw('{"directions": []}')]
    )

    response = provider.complete_json(
        system="system",
        user="user",
        schema_name="directions",
        json_schema={"type": "object"},
    )

    assert response.data == {"directions": []}
    assert response.token_in == 4
    assert response.token_out == 6
    assert response.meta["json_retries"] == 1
    assert len(provider.payloads) == 2
    assert "上一条回答不是合法" in provider.payloads[1]["messages"][-1]["content"]
    assert provider.payloads[1]["response_format"]["type"] == "json_object"


def test_complete_json_reports_error_after_all_repair_attempts() -> None:
    provider = _SequenceProvider([_raw("not json"), _raw("still not json")], retries=1)

    with pytest.raises(LLMError, match="连续 2 次返回无效 JSON"):
        provider.complete_json(system="s", user="u", schema_name="x")

    assert len(provider.payloads) == 2
