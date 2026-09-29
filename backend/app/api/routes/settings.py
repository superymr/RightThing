"""可在网页中维护的 LLM 配置。密钥只接收、不回显。"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, Request

from ...config import Settings
from ...llm import LLMError, build_provider
from ..errors import ApiError
from ..schemas import LLMSettingsResponse, LLMSettingsUpdate

router = APIRouter(prefix="/settings/llm", tags=["settings"])

_ENV_KEYS = {
    "provider": "LLM_PROVIDER",
    "base_url": "LLM_BASE_URL",
    "api_key": "LLM_API_KEY",
    "model": "LLM_MODEL",
    "strong_model": "LLM_MODEL_STRONG",
    "temperature": "LLM_TEMPERATURE",
    "timeout": "LLM_TIMEOUT",
    "max_retries": "LLM_MAX_RETRIES",
}


def _key_hint(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "已配置"
    return f"{key[:3]}…{key[-4:]}"


def _response(settings: Settings) -> LLMSettingsResponse:
    return LLMSettingsResponse(
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        strong_model=settings.llm_model_strong,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
        api_key_configured=bool(settings.llm_api_key),
        api_key_hint=_key_hint(settings.llm_api_key),
    )


def _candidate(current: Settings, body: LLMSettingsUpdate) -> Settings:
    incoming_key = body.api_key.get_secret_value().strip() if body.api_key else ""
    api_key = "" if body.clear_api_key else (incoming_key or current.llm_api_key)
    if body.provider != "mock":
        if not body.base_url:
            raise ApiError("invalid_llm_settings", "请填写 API 地址", status_code=400)
        if not body.model:
            raise ApiError("invalid_llm_settings", "请填写模型名称", status_code=400)
        if not api_key:
            raise ApiError("invalid_llm_settings", "请填写 API Key", status_code=400)
    return replace(
        current,
        llm_provider=body.provider,
        llm_base_url=body.base_url or current.llm_base_url,
        llm_api_key=api_key,
        llm_model=body.model or current.llm_model,
        llm_model_strong=body.strong_model,
        llm_temperature=body.temperature,
        llm_timeout=body.timeout,
        llm_max_retries=body.max_retries,
    )


def _quote_env(value: str) -> str:
    if not value or any(ch.isspace() or ch in "#'\"" for ch in value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _persist(settings: Settings) -> None:
    """只更新 LLM_* 行，保留用户 .env 中的其他配置与注释。"""
    path: Path = settings.config_path
    values = {
        "LLM_PROVIDER": settings.llm_provider,
        "LLM_BASE_URL": settings.llm_base_url,
        "LLM_API_KEY": settings.llm_api_key,
        "LLM_MODEL": settings.llm_model,
        "LLM_MODEL_STRONG": settings.llm_model_strong,
        "LLM_TEMPERATURE": str(settings.llm_temperature),
        "LLM_TIMEOUT": str(settings.llm_timeout),
        "LLM_MAX_RETRIES": str(settings.llm_max_retries),
    }
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    output: list[str] = []
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if key in values:
            output.append(f"{key}={_quote_env(values[key])}")
            seen.add(key)
        else:
            output.append(line)
    if output and output[-1].strip():
        output.append("")
    if not all(key in seen for key in values):
        output.append("# RightThing 网页设置：OpenAI 兼容模型接口")
        output.extend(f"{key}={_quote_env(value)}" for key, value in values.items() if key not in seen)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(temp, path)


@router.get("", response_model=LLMSettingsResponse, summary="读取模型 API 配置（密钥脱敏）")
def get_llm_settings(request: Request) -> LLMSettingsResponse:
    return _response(request.app.state.settings)


@router.post("/test", summary="测试模型 API 连通性")
def test_llm_settings(body: LLMSettingsUpdate, request: Request) -> dict:
    candidate = _candidate(request.app.state.settings, body)
    if candidate.is_mock:
        return {"ok": True, "model": "mock", "message": "本地规则引擎无需外部 API"}
    try:
        model = build_provider(candidate).check_connectivity()
    except Exception as exc:  # 网络库会抛 HTTPError，也统一成可展示错误
        raise ApiError("llm_connection_failed", f"连接失败：{exc}", status_code=400) from exc
    return {"ok": True, "model": model, "message": f"连接成功，服务端模型：{model}"}


@router.put("", response_model=LLMSettingsResponse, summary="保存并立即应用模型 API 配置")
def update_llm_settings(body: LLMSettingsUpdate, request: Request) -> LLMSettingsResponse:
    settings = _candidate(request.app.state.settings, body)
    try:
        _persist(settings)
    except OSError as exc:
        raise ApiError("settings_write_failed", f"无法保存配置：{exc}", status_code=500) from exc
    request.app.state.settings = settings
    request.app.state.orchestrator.reset(settings)
    return _response(settings)
