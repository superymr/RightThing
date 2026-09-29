"""分析相关路由：技能归一化、启动分析、任务状态与 SSE 进度。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ...services.orchestrator import AnalysisReport, AnalyzeOptions
from ...services.tasks import DONE, FAILED, Task
from ..deps import get_orchestrator, get_tasks
from ..errors import ApiError
from ..schemas import (
    AnalysisSummary,
    AnalyzeRequest,
    DirectionSummary,
    NormalizeRequest,
    NormalizeResponse,
    SkillNormalized,
    TaskStartedResponse,
)

router = APIRouter(tags=["analyze"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # nginx 默认会把响应缓冲起来，那样 SSE 就退化成「最后一次性吐出全部事件」
    "X-Accel-Buffering": "no",
}


@router.post("/skills/normalize", response_model=NormalizeResponse, summary="技能归一化预览")
def normalize_skills(payload: NormalizeRequest, request: Request) -> NormalizeResponse:
    """把用户输入映射到词表规范名。

    单独暴露成接口，是为了让前端在**跑分析之前**就把「系统是怎么理解你的输入」
    展示给用户确认 —— 归一化错了，后面所有统计都是错的。
    """
    orchestrator = get_orchestrator(request)
    items = orchestrator.normalizer.normalize_many(payload.skills)
    return NormalizeResponse(
        items=[
            SkillNormalized(
                raw=item.raw, canonical=item.canonical, category=item.category, known=item.known
            )
            for item in items
        ]
    )


def _build_options(payload: AnalyzeRequest) -> AnalyzeOptions:
    return AnalyzeOptions(
        skills=payload.skills,
        city=payload.city,
        max_directions=payload.max_directions,
        limit_per_direction=payload.limit_per_direction,
        direction_filter=payload.direction_filter,
        source_mode=payload.source_mode,
        jd_texts=payload.jd_texts,
        job_urls=payload.job_urls,
        persist=payload.persist,
    )


def _summary(report: AnalysisReport) -> dict:
    return AnalysisSummary(
        session_id=report.session_id,
        provider=report.provider,
        model=report.model,
        duration_sec=report.duration_sec,
        total_jobs=report.total_jobs,
        input_skills=report.input_skills,
        canonical_skills=[item.canonical for item in report.normalized],
        directions=[
            DirectionSummary(
                title=item.direction.title,
                match_score=item.direction.match_score,
                reason=item.direction.reason,
                keywords=item.direction.keywords,
                total_jobs=item.total,
                ok_jobs=item.ok,
                failed_jobs=item.failed,
                coverage_score=item.gap.coverage_score,
            )
            for item in report.reports
        ],
    ).model_dump()


def _task_payload(task: Task) -> dict:
    body = task.summary()
    body["result"] = task.result if task.status == DONE else None
    if task.status == FAILED:
        body["error"] = task.error
    return body


@router.post("/analyze", summary="启动一次完整分析")
def start_analysis(payload: AnalyzeRequest, request: Request):
    """默认异步：立刻返回 task_id，进度通过 SSE 推送。

    `sync=true` 会同步跑完再返回，只适合小样本或调试 —— 真实模型下
    一次分析要几十秒到几分钟，同步请求必然被浏览器或网关掐断。
    """
    options = _build_options(payload)
    if not options.skills and not options.jd_texts and not options.job_urls:
        raise ApiError(
            "empty_input",
            "skills 与 jd_texts 至少要提供一个",
            status_code=422,
            detail={"hint": '例如 {"skills": ["Python", "SQL"]}'},
        )

    # 提前构造 orchestrator：配置问题（如没填 Key）应当立刻以 503 返回，
    # 而不是等任务在后台失败了才让用户从任务状态里发现
    orchestrator = get_orchestrator(request)
    tasks = get_tasks(request)

    def worker(emit):
        report = orchestrator.analyze(options, on_event=lambda event: emit(event.to_dict()))
        return _summary(report)

    if payload.sync:
        task = tasks.run_sync("analyze", worker)
        return _task_payload(task)

    task = tasks.submit("analyze", worker)
    return JSONResponse(
        status_code=202,
        content=TaskStartedResponse(
            task_id=task.id,
            kind=task.kind,
            status=task.status,
            events_url=f"/api/tasks/{task.id}/events",
            poll_url=f"/api/tasks/{task.id}",
        ).model_dump(),
    )


@router.get("/tasks", summary="任务列表")
def list_tasks(request: Request) -> dict:
    tasks = get_tasks(request)
    return {"tasks": [task.summary() for task in tasks.list()]}


@router.get("/tasks/{task_id}", summary="任务状态（轮询兜底）")
def get_task(task_id: str, request: Request) -> dict:
    task = get_tasks(request).get(task_id)
    if task is None:
        raise ApiError("not_found", f"任务 {task_id} 不存在或已被回收", status_code=404)
    return _task_payload(task)


@router.post("/tasks/{task_id}/cancel", summary="取消运行中的任务")
def cancel_task(task_id: str, request: Request) -> dict:
    task = get_tasks(request).cancel(task_id)
    if task is None:
        raise ApiError("not_found", f"任务 {task_id} 不存在或已被回收", status_code=404)
    return {"task_id": task.id, "cancel_requested": task.cancel_requested, "status": task.status}


@router.get("/tasks/{task_id}/events", summary="任务进度（SSE）")
def task_events(task_id: str, request: Request) -> StreamingResponse:
    task = get_tasks(request).get(task_id)
    if task is None:
        raise ApiError("not_found", f"任务 {task_id} 不存在或已被回收", status_code=404)
    return StreamingResponse(
        get_tasks(request).stream(task), media_type="text/event-stream", headers=SSE_HEADERS
    )
