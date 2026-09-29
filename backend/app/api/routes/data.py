"""数据读取路由：历史会话看板、岗位详情、手动录入 JD。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ...services import dashboard, export
from ...services.orchestrator import AnalyzeOptions
from ..deps import get_db, get_orchestrator
from ..errors import ApiError
from ..schemas import ManualJobRequest

router = APIRouter(tags=["data"])


@router.get("/sessions", summary="历史分析会话列表")
def list_sessions(request: Request, limit: int = 20) -> dict:
    limit = max(1, min(limit, 100))
    return {"sessions": dashboard.list_sessions(get_db(request), limit=limit)}


@router.get("/sessions/{session_id}", summary="会话完整看板")
def get_session(session_id: int, request: Request) -> dict:
    """看板数据全部从数据库读回，不依赖任务是否还在内存里。

    因此服务重启后依然能查历史分析，多 worker 部署也不会「查不到」。
    """
    payload = dashboard.load_session(get_db(request), session_id)
    if payload is None:
        raise ApiError("not_found", f"会话 {session_id} 不存在", status_code=404)
    return payload


@router.get("/sessions/{session_id}/report.md", summary="导出 Markdown 报告")
def export_session_report(session_id: int, request: Request) -> Response:
    """导出与看板**同源**的 Markdown 报告。

    刻意复用 `dashboard.load_session()` 的那份 payload，而不是另起一条渲染路径 ——
    否则会出现「网页上写 C++ 83%、导出的 md 里写 92%」这种最伤信任的不一致，
    而且往往几个月后才被发现。
    """
    payload = dashboard.load_session(get_db(request), session_id)
    if payload is None:
        raise ApiError("not_found", f"会话 {session_id} 不存在", status_code=404)
    return Response(
        content=export.render_markdown(payload),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="rightthing-session-{session_id}.md"'
        },
    )


@router.get("/jobs/{job_id}", summary="岗位详情（原文 + 结构化结果 + 证据）")
def get_job(job_id: int, request: Request) -> dict:
    payload = dashboard.load_job(get_db(request), job_id)
    if payload is None:
        raise ApiError("not_found", f"岗位 {job_id} 不存在", status_code=404)
    return payload


@router.post("/jobs/manual", status_code=201, summary="手动录入一条 JD 并立即抽取")
def create_manual_job(payload: ManualJobRequest, request: Request) -> dict:
    """用户自己粘贴 JD 文本 —— 零爬取、零合规风险，是导入数据最稳的路径。

    实现上直接复用完整分析链路（只是限定为单条 JD、不走方向推荐），
    这样「手动录入的结果」和「自动采集的结果」在结构与统计口径上完全一致。
    """
    orchestrator = get_orchestrator(request)
    report = orchestrator.analyze(
        AnalyzeOptions(skills=[], jd_texts=[payload.text], persist=True, limit_per_direction=1)
    )
    if not report.reports or not report.reports[0].jobs:
        raise ApiError("import_failed", "JD 文本未能入库", status_code=400)

    job = report.reports[0].jobs[0]
    stored = dashboard.load_job(orchestrator.db, _job_id_of(orchestrator, job))
    return {
        "session_id": report.session_id,
        "job": stored,
        "summary": report.reports[0].aggregate.direction,
    }


def _job_id_of(orchestrator, job) -> int:
    row = orchestrator.db.query_one(
        "SELECT id FROM raw_job WHERE source = ? AND source_job_id = ?",
        (job.source, job.source_job_id),
    )
    if row is None:
        raise ApiError("not_found", "岗位入库后未能查到记录", status_code=500)
    return int(row["id"])
