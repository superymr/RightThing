"""HTTP 接口层。

分层约定（PLAN.md 第 3 节）：本层只做 HTTP 契约、参数校验与错误映射，
不写业务逻辑、不直接调用大模型、不拼 SQL。
"""

from .app import create_app

__all__ = ["create_app"]
