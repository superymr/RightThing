"""企业官网 Greenhouse Job Board API 岗位源。"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from .base import RawJob, SourceError

API_ROOT = "https://boards-api.greenhouse.io/v1/boards"


def _plain(value: object) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(html.unescape(text))).strip()


class GreenhouseJobSource:
    """读取企业主动发布在 Greenhouse 官网的公开岗位。"""

    name = "greenhouse_official"

    def __init__(
        self,
        boards: tuple[str, ...],
        cache_dir: Path,
        *,
        timeout: float = 20.0,
        cache_ttl: float = 3600.0,
        opener: Callable[[str], bytes] | None = None,
    ) -> None:
        self.boards = tuple(dict.fromkeys(board.strip().lower() for board in boards if board.strip()))
        self.cache_dir = Path(cache_dir) / "greenhouse"
        self.timeout = max(1.0, timeout)
        self.cache_ttl = max(300.0, cache_ttl)
        self._opener = opener
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.cache_hits = 0
        self.last_error = ""

    def _request_json(self, url: str) -> dict:
        self.requests += 1
        try:
            if self._opener:
                body = self._opener(url)
            else:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "JobSkillRadar/0.1 (official public job-board API)"},
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read(8_000_001)
            if len(body) > 8_000_000:
                raise SourceError("Greenhouse 响应超过 8 MB 安全上限")
            payload = json.loads(body.decode("utf-8"))
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise SourceError(f"Greenhouse 官方岗位 API 请求失败：{exc}") from exc
        self.successes += 1
        return payload

    def _board_jobs(self, board: str) -> list[dict]:
        path = self.cache_dir / f"{board}.json"
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("fetched_at", 0)) < self.cache_ttl:
                self.cache_hits += 1
                return list(cached.get("jobs") or [])
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        jobs = list(self._request_json(f"{API_ROOT}/{board}/jobs").get("jobs") or [])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fetched_at": time.time(), "jobs": jobs}, ensure_ascii=False),
            encoding="utf-8",
        )
        return jobs

    @staticmethod
    def _title_score(title: str, query: str) -> int:
        title_lower = title.lower()
        phrase = query.strip().lower()
        words = [word for word in re.findall(r"[a-z][a-z+#.-]{1,}", phrase) if len(word) > 2]
        if phrase and phrase in title_lower:
            return 100 + len(phrase)
        if words and all(word in title_lower for word in words):
            return 70 + sum(len(word) for word in words)
        return 0

    def search(self, keyword: str, *, city: str | None = None, limit: int = 30) -> list[RawJob]:
        return self.search_with_context(keyword, city=city, limit=limit)

    def search_with_context(
        self,
        keyword: str,
        *,
        city: str | None = None,
        limit: int = 30,
        deadline: float | None = None,
        on_progress=None,
    ) -> list[RawJob]:
        if not re.search(r"[A-Za-z]{2,}", keyword):
            return []
        candidates: list[tuple[int, str, dict]] = []
        for board in self.boards:
            if deadline is not None and time.monotonic() >= deadline:
                break
            try:
                entries = self._board_jobs(board)
            except SourceError:
                continue
            for entry in entries:
                title = _plain(entry.get("title"))
                score = self._title_score(title, keyword)
                location = _plain((entry.get("location") or {}).get("name"))
                if score and (not city or not location or city.lower() in location.lower()):
                    candidates.append((score, board, entry))

        jobs: list[RawJob] = []
        for _, board, entry in sorted(candidates, key=lambda item: -item[0]):
            if len(jobs) >= limit or (deadline is not None and time.monotonic() >= deadline):
                break
            job_id = str(entry.get("id") or "")
            if not job_id:
                continue
            try:
                detail = self._request_json(f"{API_ROOT}/{board}/jobs/{job_id}")
            except SourceError:
                continue
            description = _plain(detail.get("content"))
            if len(description) < 80:
                continue
            title = _plain(detail.get("title") or entry.get("title"))
            location = _plain((detail.get("location") or {}).get("name"))
            url = str(detail.get("absolute_url") or entry.get("absolute_url") or "")
            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=f"{board}:{job_id}",
                    title=title,
                    company=board,
                    city=location,
                    url=url,
                    raw_text=(
                        f"岗位名称：{title}\n公司招聘官网：{board}\n工作地点：{location}"
                        f"\n\n岗位描述：\n{description}"
                    ),
                    metadata={
                        "discovered_via": "greenhouse_official_job_board_api",
                        "board": board,
                        "updated_at": detail.get("updated_at"),
                    },
                )
            )
        return jobs

    def fetch_detail(self, job: RawJob) -> RawJob:
        return job

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": True,
            "status": "degraded" if self.failures else "ok",
            "requests": self.requests,
            "successes": self.successes,
            "failures": self.failures,
            "cached_jobs": len(list(self.cache_dir.glob("*.json"))) if self.cache_dir.exists() else 0,
            "cache_hits": self.cache_hits,
            "last_error": self.last_error,
            "policy": "official Greenhouse Job Board GET API; public company career postings only",
            "boards": list(self.boards),
        }
