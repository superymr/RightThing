"""从数据库读回一次分析。

**关键设计：看板接口不依赖进程内存。**

任务跑完的结果落在数据库里，服务重启后依然能查。如果看板要把结果留在
内存字典里，那「历史分析」就只是摆设 —— 进程一重启全没了，多 worker
部署时还会出现「请求打到另一个进程就查不到」的诡异 bug。

另一条约束：读回来的数字必须与当时看到的一致。所以持久化的是**归一化之后**
的 profile，读回时直接聚合，不再重新归一化 —— 否则词表一演进，
历史报表就悄悄变了，那不是「读回一次分析」而是「重算一次」。
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from ..analytics.aggregator import aggregate
from ..analytics.gap import compute_gap
from ..llm.schemas import JDProfile
from ..models.db import Database


def parse_input_skills(raw: str | None) -> tuple[list[str], list[str]]:
    """解析会话的输入技能。

    兼容两种格式：M1 存的纯列表，M2 起的 {"raw": [...], "canonical": [...]}。
    老库不必迁移 —— 读的时候降级处理即可。
    """
    if not raw:
        return [], []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [], []
    if isinstance(payload, list):
        return [str(item) for item in payload], []
    if isinstance(payload, dict):
        raw_skills = [str(item) for item in payload.get("raw", [])]
        canonical = [str(item) for item in payload.get("canonical", [])]
        return raw_skills, canonical
    return [], []


def list_sessions(db: Database, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT s.id, s.created_at, s.status, s.city, s.llm_provider, s.llm_model, s.input_skills, "
        "       (SELECT COUNT(*) FROM jd_profile p WHERE p.session_id = s.id) AS job_count, "
        "       (SELECT COUNT(*) FROM job_direction d WHERE d.session_id = s.id) AS direction_count "
        "FROM analysis_session s ORDER BY s.id DESC LIMIT ?",
        (limit,),
    )
    out = []
    for row in rows:
        raw_skills, _canonical = parse_input_skills(row["input_skills"])
        out.append(
            {
                "session_id": row["id"],
                "created_at": row["created_at"],
                "status": row["status"],
                "city": row["city"],
                "provider": row["llm_provider"],
                "model": row["llm_model"],
                "input_skills": raw_skills,
                "job_count": row["job_count"],
                "direction_count": row["direction_count"],
            }
        )
    return out


def load_session(db: Database, session_id: int) -> dict[str, Any] | None:
    session = db.query_one("SELECT * FROM analysis_session WHERE id = ?", (session_id,))
    if session is None:
        return None

    raw_skills, canonical_skills = parse_input_skills(session["input_skills"])
    directions = db.query(
        "SELECT * FROM job_direction WHERE session_id = ? ORDER BY id", (session_id,)
    )

    direction_payloads = [
        _build_direction(db, session_id, row, canonical_skills) for row in directions
    ]

    return {
        "session_id": session["id"],
        "created_at": session["created_at"],
        "status": session["status"],
        "city": session["city"],
        "provider": session["llm_provider"],
        "model": session["llm_model"],
        "input_skills": raw_skills,
        "canonical_skills": canonical_skills,
        "total_jobs": sum(item["total_jobs"] for item in direction_payloads),
        "directions": direction_payloads,
    }


def _build_direction(
    db: Database, session_id: int, row, canonical_skills: list[str]
) -> dict[str, Any]:
    job_rows = db.query(
        "SELECT p.id AS profile_id, p.profile_json, p.extraction_status, p.model, p.cache_hit, "
        "       j.id AS job_id, j.source, j.source_job_id, j.title, j.company, j.city, j.url "
        "FROM jd_profile p JOIN raw_job j ON j.id = p.raw_job_id "
        "WHERE p.session_id = ? AND p.direction_id = ? ORDER BY p.id",
        (session_id, row["id"]),
    )

    profiles: list[tuple[str, JDProfile]] = []
    jobs: list[dict[str, Any]] = []
    failed = 0

    for job_row in job_rows:
        jobs.append(
            {
                "job_id": job_row["job_id"],
                "profile_id": job_row["profile_id"],
                "id": job_row["source_job_id"],
                "source": job_row["source"],
                "title": job_row["title"],
                "company": job_row["company"],
                "city": job_row["city"],
                "url": job_row["url"],
                "status": job_row["extraction_status"],
            }
        )
        if job_row["extraction_status"] != "ok":
            failed += 1
            continue
        try:
            profile = JDProfile.from_dict(json.loads(job_row["profile_json"]))
        except (json.JSONDecodeError, ValueError):
            failed += 1
            continue
        profiles.append((job_row["source_job_id"] or str(job_row["job_id"]), profile))

    result = aggregate(profiles, direction=row["title"])
    gap = compute_gap(canonical_skills, result)
    valid_jobs = [job for job in jobs if job['status'] == 'ok']
    companies = {job['company'].strip() for job in valid_jobs if job['company'] and job['company'].strip()}
    sources = dict(Counter(job['source'] for job in valid_jobs))

    return {
        "direction_id": row["id"],
        "title": row["title"],
        "match_score": row["match_score"],
        "reason": row["reason"],
        "keywords": json.loads(row["keywords"] or "[]"),
        "total_jobs": len(jobs),
        "ok_jobs": len(profiles),
        "failed_jobs": failed,
        "sample_quality": {
            "company_count": len(companies),
            "source_counts": sources,
            "preliminary": len(profiles) < 20 or len(companies) < 5,
            "note": "仅代表本次采集样本，不是全市场统计；样本数量和公司分布较少时请视为初步观察。",
        },
        "languages": [s.to_dict() for s in result.languages],
        "hard_skills": [s.to_dict() for s in result.hard_skills],
        "domain_knowledge": [s.to_dict() for s in result.domain_knowledge],
        "soft_skills": [s.to_dict() for s in result.soft_skills],
        "education": [p.to_dict() for p in result.education],
        "majors": [p.to_dict() for p in result.majors],
        "experience": [p.to_dict() for p in result.experience],
        "seniority": [p.to_dict() for p in result.seniority],
        "certificates": [p.to_dict() for p in result.certificates],
        "preferred_qualifications": [p.to_dict() for p in result.preferred_qualifications],
        "gap": gap.to_dict(),
        "jobs": jobs,
    }


def load_job(db: Database, job_id: int) -> dict[str, Any] | None:
    """岗位详情：原始 JD 全文 + 最新一次的结构化结果（含 evidence，供前端高亮）。"""
    job = db.query_one("SELECT * FROM raw_job WHERE id = ?", (job_id,))
    if job is None:
        return None

    profile_row = db.query_one(
        "SELECT * FROM jd_profile WHERE raw_job_id = ? ORDER BY id DESC LIMIT 1", (job_id,)
    )

    profile: dict[str, Any] | None = None
    if profile_row is not None:
        try:
            profile = json.loads(profile_row["profile_json"])
        except json.JSONDecodeError:
            profile = None

    return {
        "job_id": job["id"],
        "source": job["source"],
        "source_job_id": job["source_job_id"],
        "title": job["title"],
        "company": job["company"],
        "city": job["city"],
        "url": job["url"],
        "raw_text": job["raw_text"],
        "fetched_at": job["fetched_at"],
        "session_id": profile_row["session_id"] if profile_row else None,
        "direction_id": profile_row["direction_id"] if profile_row else None,
        "model": profile_row["model"] if profile_row else None,
        "extraction_status": profile_row["extraction_status"] if profile_row else None,
        "cache_hit": bool(profile_row["cache_hit"]) if profile_row else False,
        "profile": profile,
    }
