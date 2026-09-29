"""Jobicy 公共远程岗位 API。

接口无需密钥，返回真实岗位全文与原始链接。按官方 fair-use 要求保留来源，
并对相同查询做一小时本地缓存。
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from .base import RawJob, SourceError

API_URL = "https://jobicy.com/api/v2/remote-jobs"


def _plain_html(value: object) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _english_query(keyword: str) -> str:
    text = keyword.strip()
    return text if re.search(r"[A-Za-z]{2,}", text) else ""


class JobicySource:
    name = "jobicy"

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout: float = 20.0,
        cache_ttl: float = 3600.0,
        opener: Callable[[str], bytes] | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) / "jobicy"
        self.timeout = max(1.0, timeout)
        self.cache_ttl = max(300.0, cache_ttl)
        self._opener = opener
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.cache_hits = 0
        self.last_error = ""

    def _cache_path(self, query: str) -> Path:
        key = hashlib.sha256(query.lower().encode()).hexdigest()[:20]
        return self.cache_dir / f"{key}.json"

    def _request(self, url: str) -> bytes:
        self.requests += 1
        try:
            if self._opener:
                body = self._opener(url)
            else:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "JobSkillRadar/0.1 (local job research tool)",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read(4_000_001)
            if len(body) > 4_000_000:
                raise SourceError("Jobicy 响应超过 4 MB 安全上限")
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise SourceError(f"Jobicy API 请求失败：{exc}") from exc
        self.successes += 1
        return body

    def _load(self, query: str) -> dict:
        path = self._cache_path(query)
        stale: dict | None = None
        try:
            stale = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(stale.get("fetched_at", 0)) < self.cache_ttl:
                self.cache_hits += 1
                return stale
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            stale = None

        params = urllib.parse.urlencode({"count": 50, "tag": query})
        try:
            payload = json.loads(self._request(f"{API_URL}?{params}").decode("utf-8"))
        except (SourceError, json.JSONDecodeError) as exc:
            if stale is not None:
                self.cache_hits += 1
                return stale
            if isinstance(exc, json.JSONDecodeError):
                self.failures += 1
                self.last_error = f"JSONDecodeError: {exc}"
                raise SourceError(f"Jobicy API 返回无效 JSON：{exc}") from exc
            raise
        cached = {"fetched_at": time.time(), "payload": payload}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
        return cached

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
        query = _english_query(keyword)
        if not query or (deadline is not None and time.monotonic() >= deadline):
            return []
        cached = self._load(query)
        payload = cached.get("payload") if isinstance(cached, dict) else {}
        jobs: list[RawJob] = []
        for entry in (payload or {}).get("jobs", []):
            title = _plain_html(entry.get("jobTitle"))
            description = _plain_html(entry.get("jobDescription"))
            url = str(entry.get("url") or "")
            location = _plain_html(entry.get("jobGeo"))
            if not title or len(description) < 80 or not url.startswith("https://"):
                continue
            if city and location and city.lower() not in location.lower():
                continue
            title_lower = title.lower()
            description_lower = description.lower()
            words = [word.lower() for word in re.findall(r"[A-Za-z][A-Za-z+#.-]{1,}", query)]
            phrase = query.strip().lower()
            relevant = phrase in title_lower or (
                words and all(word in title_lower for word in words)
            )
            if len(words) > 1:
                relevant = relevant or phrase in description_lower
            if not relevant:
                continue
            source_id = str(entry.get("id") or hashlib.sha256(url.encode()).hexdigest()[:20])
            company = _plain_html(entry.get("companyName"))
            raw_text = "\n".join(
                filter(
                    None,
                    [
                        f"岗位名称：{title}",
                        f"公司：{company}" if company else "",
                        f"工作地点：{location}" if location else "",
                        "",
                        "岗位描述：",
                        description,
                    ],
                )
            )
            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=source_id,
                    title=title,
                    company=company,
                    city=location,
                    url=url,
                    raw_text=raw_text,
                    metadata={
                        "discovered_via": "jobicy_public_api",
                        "published_at": entry.get("pubDate"),
                        "job_type": entry.get("jobType"),
                        "source_attribution": "Jobicy",
                    },
                )
            )
            if len(jobs) >= limit:
                break
        return jobs

    def fetch_detail(self, job: RawJob) -> RawJob:
        return job

    def health(self) -> dict:
        try:
            cached = len(list(self.cache_dir.glob("*.json")))
        except OSError:
            cached = 0
        return {
            "name": self.name,
            "enabled": True,
            "status": "degraded" if self.failures else "ok",
            "requests": self.requests,
            "successes": self.successes,
            "failures": self.failures,
            "cached_jobs": cached,
            "cache_hits": self.cache_hits,
            "last_error": self.last_error,
            "policy": "official public API; canonical Jobicy URLs preserved; one-hour query cache",
        }
