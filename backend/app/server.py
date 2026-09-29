"""HTTP 服务入口。

    python -m app.server                      # 默认 127.0.0.1:8000
    python -m app.cli serve --port 8080       # 等价写法
    uvicorn app.server:app --reload           # 开发热重载

交互式文档： http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import os

from .api import create_app

app = create_app()


def main() -> None:
    import uvicorn

    host = os.environ.get("JOBRADAR_HOST", "127.0.0.1")
    port = int(os.environ.get("JOBRADAR_PORT", "8000"))
    uvicorn.run("app.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
