"""LLM 层：Provider 抽象、Prompt、结构化抽取。"""

from .base import ChatProvider, LLMError, LLMResponse
from .extractor import Extractor

__all__ = ["ChatProvider", "LLMError", "LLMResponse", "Extractor", "build_provider"]


def build_provider(settings) -> ChatProvider:
    """按配置构造 Provider。延迟导入，保证 mock 模式下不依赖任何第三方库。"""
    name = (settings.llm_provider or "mock").strip().lower()
    if name == "mock":
        from .mock_provider import MockProvider

        return MockProvider()
    if name in ("openai", "compatible", "deepseek", "ollama", "vllm"):
        from .openai_provider import OpenAICompatibleProvider

        return OpenAICompatibleProvider(settings)
    raise LLMError(
        f"未知的 LLM_PROVIDER={name!r}，可选：mock | openai（任何 OpenAI 兼容端点）"
    )
