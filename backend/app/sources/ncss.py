"""国家大学生就业服务平台公开职位源。"""

from __future__ import annotations

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

BASE_URL = "https://www.ncss.cn"
LIST_URL = f"{BASE_URL}/student/jobs/jobslist/ajax/"


class _NcssParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, list[str]] = {}
        self._active: list[dict] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        for item in self._active:
            item["depth"] += 1
        values = dict(attrs)
        classes = set(values.get("class", "").split())
        key = None
        if "job-title" in classes:
            key = "title"
        elif "mainContent" in classes:
            key = "description"
        elif values.get("id") == "realCorpName":
            key = "company"
        elif values.get("id") == "companyNameMap":
            key = "address"
        if key:
            self._active.append({"key": key, "depth": 1, "parts": []})

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


class NcssSource:
    name = "ncss"

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout: float = 20.0,
        cache_ttl: float = 3600.0,
        opener: Callable[[str], bytes] | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir) / "ncss"
        self.timeout = max(1.0, timeout)
        self.cache_ttl = max(300.0, cache_ttl)
        self._opener = opener
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.cache_hits = 0
        self.last_error = ""

    def _request(self, url: str, *, accept: str = "application/json") -> bytes:
        self.requests += 1
        try:
            if self._opener:
                body = self._opener(url)
            else:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "JobSkillRadar/0.1 (+public job discovery)",
                        "Accept": accept,
                        "Referer": f"{BASE_URL}/student/jobs/index.html",
                    },
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read(3_000_001)
            if len(body) > 3_000_000:
                raise SourceError("国家大学生就业服务平台响应超过 3 MB 安全上限")
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise SourceError(f"国家大学生就业服务平台请求失败：{exc}") from exc
        self.successes += 1
        return body

    def _detail_path(self, job_id: str) -> Path:
        return self.cache_dir / "details" / f"{job_id}.json"

    def _detail(self, entry: dict) -> RawJob | None:
        job_id = str(entry.get("jobId") or "")
        if not job_id:
            return None
        path = self._detail_path(job_id)
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - float(cached.get("fetched_at", 0)) < self.cache_ttl:
                self.cache_hits += 1
                data = cached.get("job")
                return RawJob(**data) if data else None
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass

        url = f"{BASE_URL}/student/jobs/{job_id}/detail.html"
        page = self._request(url, accept="text/html").decode("utf-8", "replace")
        job = None
        if not re.search(r">\s*职位已下线\s*<", page):
            parser = _NcssParser()
            parser.feed(page)
            values = {key: _clean(items[0]) for key, items in parser.values.items() if items}
            title = values.get("title") or _clean(entry.get("jobName"))
            company = values.get("company") or _clean(entry.get("recName"))
            city = _clean(entry.get("areaCodeName")) or values.get("address", "")
            description = values.get("description", "")
            if title and len(description) >= 80:
                raw_text = "\n".join(
                    filter(
                        None,
                        [
                            f"岗位名称：{title}",
                            f"公司：{company}" if company else "",
                            f"工作地点：{city}" if city else "",
                            "",
                            "岗位描述：",
                            description,
                        ],
                    )
                )
                job = RawJob(
                    source=self.name,
                    source_job_id=job_id,
                    title=title,
                    company=company,
                    city=city,
                    url=url,
                    raw_text=raw_text,
                    metadata={
                        "discovered_via": "ncss_public_job_list",
                        "source_attribution": "国家大学生就业服务平台",
                        "degree": entry.get("degreeName"),
                        "published_at": entry.get("publishDate"),
                    },
                )
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = None
        if job:
            serialized = {
                "source": job.source,
                "source_job_id": job.source_job_id,
                "title": job.title,
                "company": job.company,
                "city": job.city,
                "url": job.url,
                "raw_text": job.raw_text,
                "metadata": job.metadata,
            }
        path.write_text(
            json.dumps({"fetched_at": time.time(), "job": serialized}, ensure_ascii=False),
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
        params = {
            "jobType": "",
            "areaCode": "",
            "jobName": keyword,
            "monthPay": "",
            "industrySectors": "",
            "property": "",
            "categoryCode": "",
            "memberLevel": "",
            "recruitType": "",
            "offset": "1",
            "limit": str(min(max(limit * 4, 20), 100)),
            "keyUnits": "",
            "degreeCode": "",
            "sourcesName": "",
            "sourcesType": "",
        }
        url = f"{LIST_URL}?{urllib.parse.urlencode(params)}"
        try:
            payload = json.loads(self._request(url).decode("utf-8"))
        except json.JSONDecodeError as exc:
            self.failures += 1
            self.last_error = f"JSONDecodeError: {exc}"
            raise SourceError(f"国家大学生就业服务平台返回无效 JSON：{exc}") from exc
        entries = (payload.get("data") or {}).get("list") or []
        jobs: list[RawJob] = []
        seen_postings: set[tuple[str, str, str]] = set()
        for index, entry in enumerate(entries, 1):
            if deadline is not None and time.monotonic() >= deadline:
                break
            entry_city = _clean(entry.get("areaCodeName"))
            if city and city not in entry_city and entry_city != "全国":
                continue
            posting_key = (
                _clean(entry.get("jobName")).lower(),
                _clean(entry.get("recName")).lower(),
                entry_city.lower(),
            )
            if posting_key in seen_postings:
                continue
            seen_postings.add(posting_key)
            job = self._detail(entry)
            if on_progress:
                on_progress(index, len(entries), len(jobs) + int(job is not None))
            if job:
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
            "policy": "public NCSS job-list endpoint and public detail pages; one-hour cache",
        }
