"""FastAPI 应用装配。

刻意不在此模块创建全局 `app` 实例：那样只要 `import` 就会连数据库、
建线程池，测试之间会互相污染。需要现成实例请用 `app.server`。
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
from ..config import Settings
from ..models.db import Database
from ..services.tasks import TaskManager
from ..utils.logging import setup_logging
from .deps import OrchestratorHolder
from .errors import install_error_handlers
from .routes import api_router
from .static import mount_frontend

logger = logging.getLogger("jobradar.api")

# 前端开发服务器（Vite / CRA）。生产环境应改成明确的域名白名单。
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

DESCRIPTION = """\
输入你会什么，反向推导出这个方向的市场真正要求什么，并画出技能缺口。

**长任务约定**：`POST /api/analyze` 默认异步，立刻返回 `task_id`；
进度通过 `GET /api/tasks/{task_id}/events`（SSE）推送，
完整结果通过 `GET /api/sessions/{session_id}` 读取。

**为什么结果不从任务里取**：看板数据全部从数据库读回，
不依赖任务是否还在内存里。因此服务重启后依然能查历史分析。
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "服务启动：provider=%s model=%s",
        app.state.settings.llm_provider,
        app.state.settings.extraction_model,
    )
    yield
    app.state.tasks.shutdown()
    logger.info("服务停止，后台任务池已关闭")


def create_app(
    settings: Settings | None = None,
    *,
    configure_logging: bool = True,
    cors_origins: list[str] | None = None,
    serve_frontend: bool | None = None,
    frontend_dist: Path | None = None,
) -> FastAPI:
    settings = settings or Settings.load()
    if configure_logging:
        setup_logging()

    app = FastAPI(
        title="RightThing 正事 API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.db = Database(settings.db_path)
    app.state.db.init_schema()
    app.state.tasks = TaskManager(max_workers=3)
    app.state.orchestrator = OrchestratorHolder(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or DEFAULT_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "%s %s -> %s (%.0fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.0f}"
        return response

    install_error_handlers(app)
    app.include_router(api_router)

    # 前端构建产物存在时由本进程托管（生产形态：一个端口搞定）。
    # 必须在 include_router 之后注册 —— 它带的是 catch-all 路由。
    #
    # serve_frontend 默认「dist 存在就挂」，但测试必须显式关掉：
    # 否则同一份测试在「本机构建过前端」和「CI 上没构建」两种环境下行为不同 ——
    # 这种随环境漂移的 200/404 是最难查的一类失败。
    mounted = False
    if serve_frontend is not False:
        mounted = mount_frontend(app, frontend_dist)

    if not mounted:

        @app.get("/", include_in_schema=False)
        def root() -> dict:
            return {
                "name": "RightThing 正事 API",
                "version": __version__,
                "docs": "/docs",
                "health": "/api/health",
                "hint": "前端未构建。开发用 `cd frontend && npm run dev`；"
                "生产用 `cd frontend && npm run build` 后重启本服务即可访问 /",
            }

    return app
