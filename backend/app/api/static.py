"""把前端构建产物挂到同一个 FastAPI 进程上（生产形态）。

**为什么值得做**：M3 的交付标准是「用户从输入技能到看到完整看板，全程无需接触命令行」。
如果看板只能通过 `npm run dev` 起另一个服务，那用户仍然要开两个终端、
还要记住 5173 和 8000 两个端口 —— 交付标准就没达到。

**与 dev 模式的关系**：开发时仍然跑 Vite dev server（有 HMR，改一行立刻看到效果），
它通过 proxy 把 `/api` 转发给后端；只有 `frontend/dist` 存在时这里才会接管。
两者互不干扰：dist 不存在时根路径回落到原来的 JSON 欢迎信息。

一个容易踩的坑：**SPA 的 history 路由需要 fallback**。
`/sessions/1` 这类路径在服务器上并没有对应文件，直接把非静态请求都回落到
`index.html` 才能让刷新页面不 404 —— 但 `/api/*` 必须排除在外，
否则一个拼错的接口路径会返回 200 + HTML，前端会把它当成「接口返回了奇怪的东西」，
排查方向会被彻底带偏。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import PROJECT_DIR

DEFAULT_DIST_DIR = PROJECT_DIR / "frontend" / "dist"

# 这些前缀属于后端自己，绝不能落到 SPA fallback 上
RESERVED_PREFIXES = ("api/", "docs", "redoc", "openapi.json")


def mount_frontend(app: FastAPI, dist_dir: Path | None = None) -> bool:
    """把 dist 挂上去。返回是否挂载成功（未构建时返回 False，调用方自行回落）。"""
    dist = Path(dist_dir or DEFAULT_DIST_DIR)
    index = dist / "index.html"
    if not index.is_file():
        return False

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    root = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):  # noqa: ANN202 - FastAPI 路由，返回类型由响应对象决定
        if full_path.startswith(RESERVED_PREFIXES):
            # 交给后端的 404 处理器，返回统一的错误契约而不是一页 HTML
            raise HTTPException(status_code=404, detail=f"未知接口：/{full_path}")

        if full_path:
            candidate = (root / full_path).resolve()
            # 防目录穿越：解析后的路径必须仍在 dist 之内
            if candidate.is_file() and candidate.is_relative_to(root):
                return FileResponse(candidate)

        # 其余一律回落到 SPA 入口，交给前端路由处理
        return FileResponse(index)

    return True
