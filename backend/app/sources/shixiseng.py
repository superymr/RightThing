"""实习僧公开职位搜索页与详情页。"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from .base import RawJob, SourceError

SEARCH_URL = "https://www.shixiseng.com/interns"


class _DetailParser(HTMLParser):
    """只采集详情页里稳定的 class 文本，不依赖第三方解析库。"""

    TARGETS = {
        "new_job_name": "title",
        "job_position": "city",
        "job_detail": "description",
        "com-name": "company",
        "com_position": "address",
    }

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, list[str]] = {}
        self._active: list[dict] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        for item in self._active:
            item["depth"] += 1
        classes = set(dict(attrs).get("class", "").split())
        for class_name, key in self.TARGETS.items():
            if class_name in classes:
                self._active.append({"key": key, "depth": 1, "parts": []})

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "br":
            self.handle_data("\n")

    def handle_endtag(self, tag: str) -> None:
        finished: list[dict] = []
        for item in self._active:
            item["depth"] -= 1
            if item["depth"] == 0:
                finished.append(item)
        for item in finished:
            self._active.remove(item)
            self.values.setdefault(item["key"], []).append("".join(item["parts"]))

    def handle_data(self, data: str) -> None:
        for item in self._active:
            item["parts"].append(data)


def _clean(value: object) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(str(value or ""))).strip()


class ShixisengSource:
    name = "shixiseng"

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout: float = 20.0,
        cache_ttl: float = 3600.0,
        opener: Callable[[str], bytes] | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) / "shixiseng"
        self.timeout = max(1.0, timeout)
        self.cache_ttl = max(300.0, cache_ttl)
        self._opener = opener
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.cache_hits = 0
        self.last_error = ""

    def _request(self, url: str) -> bytes:
        self.requests += 1
        try:
            if self._opener:
                body = self._opener(url)
            else:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "JobSkillRadar/0.1 (+public job discovery)",
                        "Accept": "text/html,application/xhtml+xml",
                    },
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read(3_000_001)
            if len(body) > 3_000_000:
                raise SourceError("实习僧页面超过 3 MB 安全上限")
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise SourceError(f"实习僧请求失败：{exc}") from exc
        self.successes += 1
        return body

    def _detail_path(self, job_id: str) -> Path:
        return self.cache_dir / "details" / f"{job_id}.json"

    def _parse_detail(self, url: str, body: bytes) -> RawJob | None:
        page = body.decode("utf-8", "replace")
        if re.search(r">\s*当前职位已下线\s*<", page):
            return None
        parser = _DetailParser()
        parser.feed(page)
        values = {key: _clean(items[0]) for key, items in parser.values.items() if items}
        title = values.get("title", "")
        description = values.get("description", "")
        company = values.get("company", "")
        city = values.get("city", "") or values.get("address", "")
        match = re.search(r"/intern/(inn_[A-Za-z0-9]+)", url)
        if not title or len(description) < 80 or not match:
            return None
        raw_text = "\n".join(
            filter(
                None,
                [
                    f"岗位名称：{title}",
                    f"公司：{company}" if company else "",
                    f"工作地点：{values.get('address') or city}" if city else "",
                    "",
                    "岗位描述：",
                    description,
                ],
            )
        )
        return RawJob(
            source=self.name,
            source_job_id=match.group(1),
            title=title,
            company=company,
            city=city,
            url=url.split("?", 1)[0],
            raw_text=raw_text,
            metadata={
                "discovered_via": "shixiseng_public_search",
                "source_attribution": "实习僧",
            },
        )

    @staticmethod
    def _serialize(job: RawJob) -> dict:
        return {
            "source": job.source,
            "source_job_id": job.source_job_id,
            "title": job.title,
            "company": job.company,
            "city": job.city,
            "url": job.url,
            "raw_text": job.raw_text,
            "metadata": job.metadata,
        }

    def _load_detail(self, url: str) -> RawJob | None:
        match = re.search(r"/intern/(inn_[A-Za-z0-9]+)", url)
        if not match:
            return None
        path = self._detail_path(match.group(1))
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("fetched_at", 0)) < self.cache_ttl:
                self.cache_hits += 1
                data = cached.get("job")
                return RawJob(**data) if data else None
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        job = self._parse_detail(url, self._request(url))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"fetched_at": time.time(), "job": self._serialize(job) if job else None},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return job

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
        if deadline is not None and time.monotonic() >= deadline:
            return []
        params = urllib.parse.urlencode({"keyword": keyword})
        page = self._request(f"{SEARCH_URL}?{params}").decode("utf-8", "replace")
        links: list[str] = []
        for path in re.findall(
            r'href=["\']([^"\']*/intern/inn_[A-Za-z0-9]+(?:\?[^"\']*)?)["\']', page
        ):
            url = urllib.parse.urljoin(SEARCH_URL, html.unescape(path))
            canonical = url.split("?", 1)[0]
            if canonical not in links:
                links.append(canonical)

        jobs: list[RawJob] = []
        for index, url in enumerate(links, 1):
            if deadline is not None and time.monotonic() >= deadline:
                break
            job = self._load_detail(url)
            if on_progress:
                on_progress(index, len(links), len(jobs) + int(job is not None))
            if not job or (city and city not in job.city):
                continue
            jobs.append(job)
            if len(jobs) >= limit:
                break
        return jobs

    def fetch_detail(self, job: RawJob) -> RawJob:
        return job

    def health(self) -> dict:
        try:
            cached = len(list((self.cache_dir / "details").glob("*.json")))
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
            "policy": "public SSR search/detail pages; robots.txt has no disallow rules; one-hour cache",
        }
