"""统一的 HTTP 错误。

**为什么不让异常自然冒泡：**
FastAPI 默认会把未捕获异常变成 500 + 纯文本 "Internal Server Error"，
前端拿不到任何可判断的信息。而这个项目有一类必须被区分的错误：
「大模型没配好 / 调不通」——它不是 bug，是配置问题，用户看完消息就能自己修。

所以统一成：

    {"error": {"code": "...", "message": "...", "detail": {...}}}
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..llm.base import LLMError

logger = logging.getLogger("jobradar.api")

CODE_BY_STATUS = {
    400: "invalid_request",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    500: "internal_error",
    503: "service_unavailable",
}


class ApiError(Exception):
    """业务错误。带上机器可读的 code，前端据此决定展示方式。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        detail: object = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


def error_response(code: str, message: str, status_code: int, detail: object = None):
    body = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return error_response(exc.code, exc.message, exc.status_code, exc.detail)

    @app.exception_handler(LLMError)
    async def _llm_error(_: Request, exc: LLMError):
        # 503 而不是 500：这是上游依赖不可用，重试或改配置就能解决，不是本服务的 bug
        return error_response(
            "llm_unavailable",
            f"大模型调用失败：{exc}",
            503,
            {"hint": "运行 `python -m app.cli doctor` 可定位是 Key、额度还是模型名的问题"},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = CODE_BY_STATUS.get(exc.status_code, "http_error")
        return error_response(code, str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        return error_response(
            "validation_error",
            "请求参数不合法",
            422,
            # exc.errors() 里可能包含不可序列化的对象，转成字符串兜底
            [{"loc": list(e.get("loc", ())), "msg": str(e.get("msg", ""))} for e in exc.errors()],
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logger.exception("未处理异常 %s %s", request.method, request.url.path)
        return error_response(
            "internal_error", f"{type(exc).__name__}: {exc}", 500
        )
