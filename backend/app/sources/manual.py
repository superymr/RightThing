"""手动粘贴数据源。

**这不是「降级方案」，而是最强的合规方案。**
用户自己从招聘网站复制 JD 文本贴进来 —— 没有任何爬取行为，也就没有任何法律风险。

CLI 用法：  --jd-file path/to/jd.txt
单文件可包含多条 JD，用一行 `=== JOB ===` 分隔。

Web 端（M2）用法：  POST /api/jobs/manual
"""

from __future__ import annotations

from pathlib import Path

from .base import RawJob

SEPARATOR = "=== JOB ==="


class ManualPasteSource:
    name = "manual"

    def __init__(self, jobs: list[RawJob] | None = None) -> None:
        self._jobs: list[RawJob] = list(jobs or [])

    # ------------------------------------------------------------------
    def add_text(self, text: str, *, title: str = "", company: str = "", city: str = "") -> RawJob:
        text = text.strip()
        if not text:
            raise ValueError("JD 文本为空")
        resolved_title = title or _guess_title(text)
        job = RawJob(
            source=self.name,
            source_job_id="",
            title=resolved_title,
            company=company,
            city=city,
            raw_text=text,
        )
        # 用内容哈希做去重键：同一份 JD 重复粘贴不会污染统计
        job.source_job_id = job.content_hash[:16]
        self._jobs.append(job)
        return job

    def load_file(self, path: Path) -> list[RawJob]:
        """从文本文件加载，支持一个文件含多条 JD（用 `=== JOB ===` 分隔）。"""
        path = Path(path)
        content = path.read_text(encoding="utf-8")
        chunks = [c.strip() for c in content.split(SEPARATOR)]
        added: list[RawJob] = []
        for chunk in chunks:
            if chunk:
                added.append(self.add_text(chunk))
        return added

    def load_files(self, paths: list[Path]) -> list[RawJob]:
        added: list[RawJob] = []
        for path in paths:
            added.extend(self.load_file(path))
        return added

    # ------------------------------------------------------------------
    def jobs(self) -> list[RawJob]:
        return list(self._jobs)

    def search(self, keyword: str, *, city: str | None = None, limit: int = 30) -> list[RawJob]:
        keyword = (keyword or "").strip()
        out = [
            job
            for job in self._jobs
            if not keyword or keyword in job.raw_text or keyword in job.title
        ]
        if city:
            out = [job for job in out if not job.city or city in job.city]
        return out[:limit]

    def fetch_detail(self, job: RawJob) -> RawJob:
        return job


def _guess_title(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line:
            for prefix in ("岗位名称：", "职位名称：", "岗位：", "职位："):
                if line.startswith(prefix):
                    return line[len(prefix):].strip()[:40]
            return line[:40]
    return "未标注岗位"
