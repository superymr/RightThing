"""内置样例数据源。

M1 的主路径。存在的理由不是「偷懒」，而是：
- 让整条分析链路在**零外部依赖、零合规风险**的前提下可被反复验证；
- 提供一组**固定的回归基线**：改了聚合逻辑，排名变化一眼可见；
- 新协作者 clone 下来 30 秒内就能看到完整结果。

样例文件结构（backend/data/samples/*.json）：
{
  "direction": "机器人算法工程师",
  "keywords": [...],            // 用于方向匹配与检索
  "signature_skills": [...],    // mock provider 用它算方向匹配度
  "related_titles": [...],
  "jobs": [ {...} ]
}
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import RawJob, build_raw_text


class SampleSource:
    name = "sample"

    def __init__(self, sample_dir: Path) -> None:
        self.sample_dir = Path(sample_dir)
        self._cache: list[tuple[dict, list[RawJob]]] | None = None

    # ------------------------------------------------------------------
    def _load(self) -> list[tuple[dict, list[RawJob]]]:
        if self._cache is not None:
            return self._cache

        bundles: list[tuple[dict, list[RawJob]]] = []
        if not self.sample_dir.is_dir():
            self._cache = bundles
            return bundles

        for path in sorted(self.sample_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            direction = payload.get("direction", path.stem)
            jobs: list[RawJob] = []
            for entry in payload.get("jobs", []):
                jobs.append(self._to_raw_job(entry, direction=direction))
            bundles.append((payload, jobs))

        self._cache = bundles
        return bundles

    def _to_raw_job(self, entry: dict, *, direction: str) -> RawJob:
        responsibilities = list(entry.get("responsibilities", []))
        requirements = list(entry.get("requirements", []))
        extra = list(entry.get("preferred", []))
        title = entry.get("title", "未标注岗位")
        company = entry.get("company", "")
        city = entry.get("city", "")

        raw_text = entry.get("raw_text") or build_raw_text(
            title=title,
            company=company,
            city=city,
            responsibilities=responsibilities,
            requirements=requirements,
            extra_lines=extra,
        )
        return RawJob(
            source=self.name,
            source_job_id=entry.get("id", ""),
            title=title,
            company=company,
            city=city,
            url=entry.get("url", ""),
            raw_text=raw_text,
            direction=direction,
        )

    # ------------------------------------------------------------------
    def directions(self) -> list[str]:
        return [payload.get("direction", "") for payload, _ in self._load()]

    def search(self, keyword: str, *, city: str | None = None, limit: int = 30) -> list[RawJob]:
        """按关键词匹配样例岗位：方向名 > 方向关键词 > 岗位标题。"""
        keyword = (keyword or "").strip()
        if not keyword:
            return []

        scored: list[tuple[int, RawJob]] = []
        for payload, jobs in self._load():
            direction = payload.get("direction", "")
            keywords = [k for k in payload.get("keywords", [])]
            related = [k for k in payload.get("related_titles", [])]

            if keyword == direction:
                weight = 100
            elif keyword in keywords:
                weight = 80
            elif keyword in related:
                weight = 60
            elif keyword and keyword in direction:
                weight = 40
            else:
                weight = 0

            for job in jobs:
                if city and job.city and city not in job.city:
                    continue
                if weight:
                    scored.append((weight, job))
                elif keyword in job.title:
                    scored.append((10, job))

        scored.sort(key=lambda item: (-item[0], item[1].source_job_id))
        return [job for _, job in scored[:limit]]

    def all_jobs(self) -> list[RawJob]:
        return [job for _, jobs in self._load() for job in jobs]

    def fetch_detail(self, job: RawJob) -> RawJob:
        return job
