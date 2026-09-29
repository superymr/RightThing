"""Provider 抽象层。

契约：Provider 只负责「把一段对话变成合法 JSON」，不理解业务语义。
换模型 = 换 Provider 实现，其余代码零改动。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class LLMError(RuntimeError):
    """LLM 调用失败（网络、鉴权、限流、返回非法 JSON 等）。"""


@dataclass
class LLMResponse:
    """一次 LLM 调用的结果。"""

    data: dict[str, Any]
    model: str = ""
    token_in: int = 0
    token_out: int = 0
    raw_text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ChatProvider(Protocol):
    """所有 Provider 必须实现的接口。"""

    name: str
    model_name: str

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """返回已解析为 dict 的 JSON 结果。

        约定：
        - 失败必须抛 LLMError，不允许静默返回空结果；
        - 不允许在 Provider 内部做「猜」或补全缺失字段，那是 extractor 的职责。
        """
        ...
