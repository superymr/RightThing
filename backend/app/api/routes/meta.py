"""元信息路由：健康检查、可选方向列表。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ... import __version__
from ...llm.base import LLMError
from ...sources import SampleSource
from ..deps import get_settings
from ..errors import ApiError
from ..schemas import HealthResponse

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse, summary="健康检查")
def health(request: Request, deep: bool = False) -> HealthResponse:
    """`deep=true` 会真的调用一次大模型（有成本，别放进探针）。"""
    settings = get_settings(request)
    holder = request.app.state.orchestrator

    llm_ready = settings.is_mock or bool(settings.llm_api_key)
    detail = "本地规则引擎，无需外部依赖" if settings.is_mock else ""
    status = "ok" if llm_ready else "degraded"

    if deep:
        try:
            provider = holder.get().provider
            probe = getattr(provider, "check_connectivity", None)
            if callable(probe):
                actual = probe()
                detail = f"大模型连通正常（服务端返回模型 {actual}）"
            else:
                detail = "本地规则引擎，跳过连通性检查"
            llm_ready = True
        except (ApiError, LLMError) as exc:
            # 健康检查不该因为依赖挂掉就 500：它存在的意义正是把问题报告出来
            llm_ready = False
            status = "degraded"
            detail = str(exc)

    return HealthResponse(
        status=status,
        version=__version__,
        provider=settings.llm_provider,
        model=settings.extraction_model,
        cache_enabled=settings.cache_enabled,
        prompt_version=settings.prompt_version,
        database=str(settings.db_path),
        llm_ready=llm_ready,
        detail=detail,
    )


@router.get("/directions", summary="岗位数据源配置（兼容旧接口名）")
def directions(request: Request) -> dict:
    settings = get_settings(request)
    source = SampleSource(settings.sample_dir)
    sample_directions = source.directions() if settings.enable_sample_source else []
    sample_jobs = len(source.all_jobs()) if settings.enable_sample_source else 0
    return {
        "directions": sample_directions,
        "total_jobs": sample_jobs,
        "source": str(settings.sample_dir),
        "live_sources_enabled": settings.enable_live_sources,
        "sample_source_enabled": settings.enable_sample_source,
    }


@router.get("/sources/health", summary="采集源健康状态")
def source_health(request: Request) -> dict:
    holder = request.app.state.orchestrator
    return {
        "live_sources_enabled": get_settings(request).enable_live_sources,
        "sources": holder.get().source_health(),
    }
