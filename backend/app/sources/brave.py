"""可选的 Brave Web Search 岗位源（需要用户自己的 API Key）。"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

from .base import RawJob, SourceError

API_URL = "https://api.search.brave.com/res/v1/web/search"


class BraveJobSearchSource:
    name = "brave_search"

    def __init__(self, api_key: str, *, timeout: float = 15.0) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.last_error = ""

    def search(self, keyword: str, *, city: str | None = None, limit: int = 30) -> list[RawJob]:
        query = f'"{keyword}" (招聘 OR careers OR jobs) (岗位职责 OR 任职要求 OR requirements)'
        if city:
            query += f" {city}"
        params = urllib.parse.urlencode(
            {
                "q": query,
                "count": min(max(limit, 1), 20),
                "country": "CN",
                "search_lang": "zh-hans",
                "extra_snippets": "true",
                "freshness": "py",
            }
        )
        request = urllib.request.Request(
            f"{API_URL}?{params}",
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
        )
        self.requests += 1
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read(2_000_000).decode("utf-8"))
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise SourceError(f"Brave Search 请求失败：{exc}") from exc
        self.successes += 1
        jobs: list[RawJob] = []
        for item in payload.get("web", {}).get("results", []):
            url = str(item.get("url") or "")
            title = str(item.get("title") or "").strip()
            snippets = [str(item.get("description") or "").strip()]
            snippets.extend(str(value).strip() for value in item.get("extra_snippets") or [])
            text = "\n".join(value for value in snippets if value)
            if not url.startswith("https://") or not title or len(text) < 40:
                continue
            source_id = hashlib.sha256(url.encode()).hexdigest()[:20]
            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=source_id,
                    title=title[:120],
                    company=urllib.parse.urlparse(url).hostname or "",
                    city=city or "",
                    url=url,
                    raw_text=f"岗位页面标题：{title}\n\n搜索索引摘要：\n{text}",
                    metadata={"discovered_via": "brave_web_search", "is_search_excerpt": True},
                )
            )
        return jobs[:limit]

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
            "cached_jobs": 0,
            "last_error": self.last_error,
            "policy": "official Brave Web Search API; user-provided server-side API key",
        }
