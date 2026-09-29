"""牛客公开 sitemap 岗位源。

合规边界：牛客 ``robots.txt`` 禁止 ``/search``，因此本实现不访问搜索页或内部接口。
岗位发现只读取站点主动公开的 sitemap，详情只读取 sitemap 列出的
``/jobs/detail/*`` 页面。请求低频、数量有上限并落本地缓存。
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .base import RawJob, SourceError

ROBOTS_URL = "https://www.nowcoder.com/robots.txt"
SITEMAP_URL = "https://www.nowcoder.com/nowpick/sitemap1.xml"
DETAIL_PREFIX = "https://www.nowcoder.com/jobs/detail/"
STATE_MARKER = "window.__INITIAL_STATE__="

# sitemap 只提供详情 URL，没有站内搜索能力。为了让模型生成的细粒度岗位名
# （如“短视频剪辑师”）能命中真实页面中的近义标题（如“视频编导”），在本地
# 缓存检索时做一层可解释的领域词扩展。这里只影响召回，最终分析仍基于原始 JD。
TERM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("视频剪辑", "剪辑", "视频", "后期", "编导"),
    ("短视频", "视频", "新媒体"),
    ("影视", "影片", "节目", "纪录片", "后期"),
    ("包装", "动效", "动画", "特效"),
    ("电商", "带货", "广告", "信息流", "投放", "素材"),
)


def _plain(value: object) -> str:
    return html.unescape(str(value or "")).strip()


def _variants(keyword: str) -> list[str]:
    text = re.sub(r"\s+", "", keyword).lower()
    values = {text}
    for suffix in ("算法工程师", "开发工程师", "工程师", "研究员", "专家", "岗位"):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            values.add(text[: -len(suffix)])
    return sorted((item for item in values if len(item) >= 2), key=len, reverse=True)


def _search_terms(keyword: str) -> list[str]:
    """从岗位短语得到适合本地召回的核心词及近义词。"""
    normalized = re.sub(r"\s+", "", keyword).lower()
    terms = set(_variants(keyword))
    for group in TERM_GROUPS:
        if any(term in normalized for term in group):
            terms.update(group)
    return sorted((term for term in terms if len(term) >= 2), key=len, reverse=True)


class NowcoderSource:
    name = "nowcoder"

    def __init__(
        self,
        cache_dir: Path,
        *,
        timeout: float = 20.0,
        min_interval: float = 0.35,
        scan_limit: int = 120,
        search_budget: float = 10.0,
        opener: Callable[[str], bytes] | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.timeout = max(1.0, timeout)
        self.min_interval = max(0.0, min_interval)
        self.scan_limit = max(1, scan_limit)
        self.search_budget = max(1.0, search_budget)
        self._opener = opener
        self._last_request = 0.0
        self._lock = threading.RLock()
        self._jobs: dict[str, RawJob] | None = None
        self._failed_urls: set[str] = set()
        self._urls: list[str] | None = None
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.last_error = ""

    @property
    def _jobs_path(self) -> Path:
        return self.cache_dir / "nowcoder-jobs.json"

    @property
    def _sitemap_path(self) -> Path:
        return self.cache_dir / "nowcoder-sitemap.json"

    @staticmethod
    def supports_url(url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme == "https" and parsed.hostname in {"www.nowcoder.com", "nowcoder.com"} and parsed.path.startswith("/jobs/detail/")

    def _request(self, url: str, *, max_bytes: int) -> bytes:
        if self._opener is not None:
            return self._opener(url)
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "JobSkillRadar/0.1 (local research tool; sitemap crawler)",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        self.requests += 1
        self._last_request = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise SourceError(f"响应超过安全上限：{url}")
            self.successes += 1
            return body
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            raise SourceError(f"牛客请求失败：{url}（{exc}）") from exc

    def _check_robots(self) -> None:
        text = self._request(ROBOTS_URL, max_bytes=128_000).decode("utf-8", "replace")
        disallowed = []
        applies = False
        for raw in text.splitlines():
            key, _, value = raw.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                applies = value == "*"
            elif applies and key == "disallow" and value:
                disallowed.append(value)
        detail_path = "/jobs/detail/"
        if any(detail_path.startswith(path) for path in disallowed):
            raise SourceError("牛客 robots.txt 当前不允许读取岗位详情，已停止在线采集")

    def _load_urls(self) -> list[str]:
        if self._urls is not None:
            return self._urls
        now = time.time()
        try:
            cached = json.loads(self._sitemap_path.read_text(encoding="utf-8"))
            if now - float(cached.get("fetched_at", 0)) < 24 * 3600:
                self._urls = [str(url) for url in cached.get("urls", [])]
                return self._urls
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

        self._check_robots()
        xml = self._request(SITEMAP_URL, max_bytes=2_000_000).decode("utf-8", "replace")
        urls = [
            html.unescape(url)
            for url in re.findall(r"<loc>\s*(https://www\.nowcoder\.com/jobs/detail/[^<]+)</loc>", xml)
        ]
        if not urls:
            raise SourceError("牛客岗位 sitemap 中没有可用详情链接")
        self._urls = urls
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._sitemap_path.write_text(
            json.dumps({"fetched_at": now, "urls": urls}, ensure_ascii=False), encoding="utf-8"
        )
        return urls

    def _load_jobs(self) -> dict[str, RawJob]:
        if self._jobs is not None:
            return self._jobs
        jobs: dict[str, RawJob] = {}
        try:
            payload = json.loads(self._jobs_path.read_text(encoding="utf-8"))
            self._failed_urls = {str(url) for url in payload.get("failed_urls", [])}
            for entry in payload.get("jobs", []):
                job = RawJob(**entry)
                jobs[job.url] = job
        except (OSError, TypeError, json.JSONDecodeError):
            pass
        self._jobs = jobs
        return jobs

    def _save_jobs(self) -> None:
        assert self._jobs is not None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._jobs_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "jobs": [asdict(job) for job in self._jobs.values()],
                    "failed_urls": sorted(self._failed_urls),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(self._jobs_path)

    @staticmethod
    def _parse_detail(url: str, body: bytes) -> RawJob:
        page = body.decode("utf-8", "replace")
        position = page.find(STATE_MARKER)
        if position < 0:
            raise SourceError(f"牛客岗位页缺少服务端数据：{url}")
        start = position + len(STATE_MARKER)
        try:
            state, _ = json.JSONDecoder().raw_decode(page[start:])
            detail = state["store"]["jobDetail"]["detail"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SourceError(f"牛客岗位页结构已变化：{url}") from exc

        try:
            extension = json.loads(detail.get("ext") or "{}")
        except (TypeError, json.JSONDecodeError):
            extension = {}
        title = _plain(detail.get("jobName"))
        responsibilities = _plain(extension.get("infos"))
        requirements = _plain(extension.get("requirements"))
        company_info = detail.get("recommendInternCompany") or detail.get("company") or {}
        company = _plain(company_info.get("companyName") or company_info.get("companyShortName"))
        city = _plain(detail.get("jobCity") or " / ".join(detail.get("jobCityList") or []))
        job_id = _plain(detail.get("id")) or Path(urllib.parse.urlparse(url).path).name
        if not title or not (responsibilities or requirements):
            raise SourceError(f"牛客岗位页缺少标题或 JD 正文：{url}")

        lines = [f"岗位名称：{title}"]
        if company:
            lines.append(f"公司：{company}")
        if city:
            lines.append(f"工作地点：{city}")
        if responsibilities:
            lines.extend(["", "岗位职责：", responsibilities])
        if requirements:
            lines.extend(["", "任职要求：", requirements])
        return RawJob(
            source="nowcoder",
            source_job_id=job_id,
            title=title,
            company=company,
            city=city,
            url=url.split("?", 1)[0],
            raw_text="\n".join(lines),
            metadata={
                "status": detail.get("status"),
                "updated_at": detail.get("updateTime"),
                "discovered_via": "public_sitemap",
            },
        )

    def _fetch_url(self, url: str) -> RawJob:
        canonical = url.split("?", 1)[0]
        body = self._request(url, max_bytes=1_500_000)
        return self._parse_detail(canonical, body)

    @staticmethod
    def _score(job: RawJob, keyword: str) -> int:
        title = re.sub(r"\s+", "", job.title).lower()
        body = re.sub(r"\s+", "", job.raw_text).lower()
        score = 0
        for variant in _variants(keyword):
            if variant in title:
                score = max(score, 100 + len(variant))
            elif variant in body:
                score = max(score, 20 + len(variant))
        # 完整短语优先；若没有完整命中，再按核心词的命中数量排序。标题命中
        # 权重大于正文，避免正文偶然提到一次“视频”排在真正相关岗位之前。
        title_hits = [term for term in _search_terms(keyword) if term in title]
        creative_terms = ("视频剪辑", "剪辑", "视频", "后期", "编导", "包装", "动效", "动画", "特效")
        creative_query = any(term in re.sub(r"\s+", "", keyword).lower() for term in creative_terms)
        # “电商短视频剪辑”会扩展出“电商/投放”等场景词，但仅有场景词的
        # “电商客服”“投放算法”并不是剪辑岗位；创作类查询必须在标题中同时
        # 出现创作角色词，才允许进入候选集。
        if creative_query and not any(term in title for term in creative_terms):
            title_hits = []
        if title_hits:
            score = max(score, 40 + sum(len(term) for term in title_hits))
        return score

    def search(self, keyword: str, *, city: str | None = None, limit: int = 30) -> list[RawJob]:
        return self.search_with_context(
            keyword,
            city=city,
            limit=limit,
            deadline=time.monotonic() + self.search_budget,
        )

    def search_with_context(
        self,
        keyword: str,
        *,
        city: str | None = None,
        limit: int = 30,
        deadline: float | None = None,
        on_progress: Callable[[int, int, int], None] | None = None,
    ) -> list[RawJob]:
        keyword = keyword.strip()
        if not keyword:
            return []
        with self._lock:
            jobs = self._load_jobs()
            scored: dict[str, tuple[int, RawJob]] = {}

            def consider(job: RawJob) -> None:
                if city and job.city and city not in job.city:
                    return
                score = self._score(job, keyword)
                if score:
                    scored[job.source_job_id] = (score, job)

            for job in jobs.values():
                consider(job)
            scanned = 0
            dirty = False
            if len(scored) < limit:
                for url in self._load_urls():
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    canonical = url.split("?", 1)[0]
                    if canonical in jobs or canonical in self._failed_urls:
                        continue
                    if scanned >= self.scan_limit:
                        break
                    scanned += 1
                    if on_progress and (scanned == 1 or scanned % 10 == 0):
                        on_progress(scanned, self.scan_limit, len(scored))
                    try:
                        job = self._fetch_url(url)
                    except SourceError:
                        self._failed_urls.add(canonical)
                        dirty = True
                        continue
                    jobs[canonical] = job
                    dirty = True
                    consider(job)
                    if len(scored) >= limit:
                        break
            if dirty:
                self._save_jobs()
            return [job for _, job in sorted(scored.values(), key=lambda item: (-item[0], item[1].source_job_id))[:limit]]

    def load_url(self, url: str) -> RawJob:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"www.nowcoder.com", "nowcoder.com"}:
            raise SourceError("目前 URL 导入仅支持 https://www.nowcoder.com/jobs/detail/*")
        if not parsed.path.startswith("/jobs/detail/"):
            raise SourceError("牛客 URL 必须是 /jobs/detail/* 岗位详情页")
        canonical = f"https://www.nowcoder.com{parsed.path}"
        with self._lock:
            cached = self._load_jobs().get(canonical)
            if cached:
                return cached
            job = self._fetch_url(canonical)
            self._jobs[canonical] = job
            self._save_jobs()
            return job

    def fetch_detail(self, job: RawJob) -> RawJob:
        if job.raw_text:
            return job
        return self._fetch_url(job.url)

    def health(self) -> dict:
        cached = len(self._load_jobs())
        return {
            "name": self.name,
            "enabled": True,
            "status": "degraded" if self.failures or self.last_error else "ok",
            "requests": self.requests,
            "successes": self.successes,
            "failures": self.failures,
            "cached_jobs": cached,
            "last_error": self.last_error,
            "policy": "public sitemap + /jobs/detail only; /search is not accessed",
        }
