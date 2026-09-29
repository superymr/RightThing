"""日志配置。

用标准库 logging 而不是 structlog：M2 只有单进程 + 少量并发，
引入结构化日志库的收益抵不过多一个依赖的成本。日志格式刻意保留
「时间 / 级别 / 模块名」三要素，方便按模块过滤。
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False


def setup_logging(level: str | None = None) -> None:
    """幂等：uvicorn 自己也会配 logging，重复配置会把已有 handler 叠一层。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    resolved = (level or os.environ.get("JOBRADAR_LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, resolved, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-22s | %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    # 访问日志由我们自己的中间件输出（带耗时），关掉 uvicorn 的以免重复
    logging.getLogger("uvicorn.access").disabled = True
    _CONFIGURED = True
