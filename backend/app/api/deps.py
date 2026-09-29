"""依赖注入。

所有依赖都从 `request.app.state` 取，而不是模块级单例。
这样测试可以构造一个「配置指向临时数据库」的 app 实例，
不必去动全局状态 —— 模块级单例是测试互相污染最常见的来源。
"""

from __future__ import annotations

from fastapi import Request

from ..config import Settings
from ..llm.base import LLMError
from ..models.db import Database
from ..services.orchestrator import Orchestrator
from ..services.tasks import TaskManager
from .errors import ApiError


class OrchestratorHolder:
    """延迟构造 Orchestrator。

    为什么不在启动时构造：LLM_PROVIDER=openai 但没填 Key 时构造会抛异常。
    那不该让整个服务起不来 —— 健康检查、历史看板这些接口跟大模型没关系，
    应该照常可用。所以推迟到真正要用的时候，并给出 503 + 可执行的提示。
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._instance: Orchestrator | None = None

    def get(self) -> Orchestrator:
        if self._instance is None:
            try:
                self._instance = Orchestrator(self._settings)
            except LLMError as exc:
                raise ApiError(
                    "llm_not_configured",
                    str(exc),
                    status_code=503,
                    detail={"hint": "编辑项目根目录的 .env 填写 LLM_API_KEY 后重启服务"},
                ) from exc
        return self._instance

    def reset(self, settings: Settings) -> None:
        """配置变更后丢弃旧实例，下一次请求按新配置重新构造。"""
        self._settings = settings
        self._instance = None


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_tasks(request: Request) -> TaskManager:
    return request.app.state.tasks


def get_orchestrator(request: Request) -> Orchestrator:
    holder: OrchestratorHolder = request.app.state.orchestrator
    return holder.get()
