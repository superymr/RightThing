"""Arbeitnow 公共 Job Board API 岗位源。"""

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

API_URL = "https://www.arbeitnow.com/api/job-board-api"


def _plain(value: object) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


class ArbeitnowSource:
    name = "arbeitnow"

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout: float = 20.0,
        pages: int = 3,
        cache_ttl: float = 3600.0,
        opener: Callable[[str], bytes] | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) / "arbeitnow"
        self.timeout = max(1.0, timeout)
        self.pages = max(1, min(pages, 10))
        self.cache_ttl = max(300.0, cache_ttl)
        self._opener = opener
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.cache_hits = 0
        self.last_error = ""

    def _request(self, url: str) -> dict:
        self.requests += 1
        try:
            if self._opener:
                body = self._opener(url)
            else:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 JobSkillRadar/0.1",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read(8_000_001)
            if len(body) > 8_000_000:
                raise SourceError("Arbeitnow 响应超过 8 MB 安全上限")
            payload = json.loads(body.decode("utf-8"))
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise SourceError(f"Arbeitnow API 请求失败：{exc}") from exc
        self.successes += 1
        return payload

    def _catalog(self) -> list[dict]:
        path = self.cache_dir / "catalog.json"
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("fetched_at", 0)) < self.cache_ttl:
                self.cache_hits += 1
                return list(cached.get("jobs") or [])
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass

        jobs: list[dict] = []
        for page in range(1, self.pages + 1):
            payload = self._request(f"{API_URL}?page={page}")
            jobs.extend(payload.get("data") or [])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fetched_at": time.time(), "jobs": jobs}, ensure_ascii=False),
            encoding="utf-8",
        )
        return jobs

    @staticmethod
    def _score(title: str, query: str) -> int:
        title_lower = title.lower()
        phrase = query.strip().lower()
        words = [word for word in re.findall(r"[a-z][a-z+#.-]{1,}", phrase) if len(word) > 2]
        if phrase and phrase in title_lower:
            return 100 + len(phrase)
        if words and all(word in title_lower for word in words):
            return 70 + sum(len(word) for word in words)
        media_roles = ("editor", "editing", "artist", "designer", "producer", "lead")
        if "video" in words and "video" in title_lower and any(role in title_lower for role in media_roles):
            return 55
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
        if deadline is not None and time.monotonic() >= deadline:
            return []
        scored: list[tuple[int, dict]] = []
        for entry in self._catalog():
            title = _plain(entry.get("title"))
            score = self._score(title, keyword)
            location = _plain(entry.get("location"))
            if score and (not city or not location or city.lower() in location.lower()):
                scored.append((score, entry))

        jobs: list[RawJob] = []
        seen_urls: set[str] = set()
        for _, entry in sorted(scored, key=lambda item: -item[0]):
            title = _plain(entry.get("title"))
            description = _plain(entry.get("description"))
            url = str(entry.get("url") or "")
            if len(description) < 80 or not url.startswith("https://"):
                continue
            canonical_url = url.split("?", 1)[0].lower()
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)
            source_id = str(entry.get("slug") or url.rsplit("/", 1)[-1])
            company = _plain(entry.get("company_name"))
            location = _plain(entry.get("location"))
            jobs.append(
                RawJob(
                    source=self.name,
                    source_job_id=source_id,
                    title=title,
                    company=company,
                    city=location,
                    url=url,
                    raw_text=(
                        f"岗位名称：{title}\n公司：{company}\n工作地点：{location}"
                        f"\n\n岗位描述：\n{description}"
                    ),
                    metadata={
                        "discovered_via": "arbeitnow_public_api",
                        "created_at": entry.get("created_at"),
                        "remote": entry.get("remote"),
                        "source_attribution": "Arbeitnow",
                    },
                )
            )
            if len(jobs) >= limit:
                break
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
            "cached_jobs": 1 if (self.cache_dir / "catalog.json").is_file() else 0,
            "cache_hits": self.cache_hits,
            "last_error": self.last_error,
            "policy": "public job-board API; source attribution and canonical URLs preserved; one-hour cache",
        }
