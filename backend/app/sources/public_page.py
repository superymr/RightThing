"""安全导入公开招聘网页，优先解析 schema.org JobPosting JSON-LD。"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Callable

from .base import RawJob, SourceError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.json_scripts: list[str] = []
        self._script: list[str] | None = None
        self.visible: list[str] = []
        self.title: list[str] = []
        self._in_title = False
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._script = []
        elif tag in {"script", "style", "noscript", "svg"}:
            self._hidden += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.json_scripts.append("".join(self._script))
            self._script = None
        elif tag in {"script", "style", "noscript", "svg"} and self._hidden:
            self._hidden -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)
        elif self._in_title:
            self.title.append(data)
        elif not self._hidden and data.strip():
            self.visible.append(data.strip())


def _job_postings(value):
    if isinstance(value, list):
        for item in value:
            yield from _job_postings(item)
    elif isinstance(value, dict):
        kind = value.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            yield value
        for item in value.get("@graph", []):
            yield from _job_postings(item)


def _text(value) -> str:
    if isinstance(value, str):
        parser = _PageParser()
        parser.feed(value)
        return html.unescape(" ".join(parser.visible) or value).strip()
    if isinstance(value, list):
        return "\n".join(filter(None, (_text(item) for item in value)))
    if isinstance(value, dict):
        return _text(value.get("name") or value.get("value") or value.get("credentialCategory"))
    return ""


class PublicJobPageSource:
    name = "public_job_page"
    # 只负责用户指定 URL 的导入，不参与主动检索配额与时间预算分配。
    supports_discovery = False

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        fetcher: Callable[[str], tuple[bytes, str, str]] | None = None,
    ) -> None:
        self.timeout = timeout
        self._fetcher = fetcher
        self.requests = 0
        self.successes = 0
        self.failures = 0
        self.last_error = ""

    @staticmethod
    def supports_url(url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme == "https" and parsed.hostname not in {
            "nowcoder.com",
            "www.nowcoder.com",
        }

    @staticmethod
    def _validate_public(url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise SourceError("岗位 URL 必须是无账号信息的公开 HTTPS 地址")
        try:
            addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise SourceError(f"无法解析岗位网站域名：{parsed.hostname}") from exc
        for entry in addresses:
            address = ipaddress.ip_address(entry[4][0])
            if not address.is_global:
                raise SourceError("拒绝访问内网、回环、链路本地或保留地址")

    def _fetch(self, url: str) -> tuple[bytes, str, str]:
        if self._fetcher:
            return self._fetcher(url)
        current = url
        opener = urllib.request.build_opener(_NoRedirect())
        for _ in range(4):
            self._validate_public(current)
            request = urllib.request.Request(
                current, headers={"User-Agent": "JobSkillRadar/0.1 (user-requested job import)"}
            )
            try:
                with opener.open(request, timeout=self.timeout) as response:
                    final_url = response.geturl()
                    self._validate_public(final_url)
                    content_type = response.headers.get("Content-Type", "")
                    body = response.read(2_000_001)
            except urllib.error.HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308} and exc.headers.get("Location"):
                    current = urllib.parse.urljoin(current, exc.headers["Location"])
                    continue
                raise SourceError(f"岗位页面请求失败：HTTP {exc.code}") from exc
            except (OSError, urllib.error.URLError) as exc:
                raise SourceError(f"岗位页面请求失败：{exc}") from exc
            if len(body) > 2_000_000:
                raise SourceError("岗位页面超过 2 MB 安全上限")
            return body, final_url, content_type
        raise SourceError("岗位页面重定向次数过多")

    @staticmethod
    def _parse(url: str, body: bytes, content_type: str) -> RawJob:
        if "html" not in content_type.lower() and content_type:
            raise SourceError("岗位 URL 返回的不是 HTML 页面")
        page = body.decode("utf-8", "replace")
        parser = _PageParser()
        parser.feed(page)
        posting = None
        for raw in parser.json_scripts:
            try:
                posting = next(_job_postings(json.loads(raw)), None)
            except (json.JSONDecodeError, TypeError):
                continue
            if posting:
                break

        if posting:
            title = _text(posting.get("title") or posting.get("name"))
            company = _text(posting.get("hiringOrganization"))
            location = posting.get("jobLocation") or {}
            if isinstance(location, list):
                location = location[0] if location else {}
            address = location.get("address", {}) if isinstance(location, dict) else {}
            city = " ".join(
                filter(None, [_text(address.get("addressLocality")), _text(address.get("addressRegion"))])
            )
            fields = [
                ("岗位描述", posting.get("description")),
                ("岗位职责", posting.get("responsibilities")),
                ("技能要求", posting.get("skills")),
                ("任职资格", posting.get("qualifications")),
                ("经验要求", posting.get("experienceRequirements")),
                ("教育要求", posting.get("educationRequirements")),
            ]
            sections = [f"岗位名称：{title}"]
            if company:
                sections.append(f"公司：{company}")
            if city:
                sections.append(f"工作地点：{city}")
            for label, value in fields:
                rendered = _text(value)
                if rendered:
                    sections.extend(["", f"{label}：", rendered])
            raw_text = "\n".join(sections)
        else:
            title = html.unescape(" ".join(parser.title)).strip()[:120]
            visible = re.sub(r"\s+", " ", " ".join(parser.visible)).strip()
            if not title or len(visible) < 200:
                raise SourceError("页面没有 JobPosting 结构化数据，且可读正文不足")
            company, city = urllib.parse.urlparse(url).hostname or "", ""
            raw_text = f"岗位页面标题：{title}\n\n页面正文：\n{visible[:50_000]}"

        if not title or len(raw_text) < 80:
            raise SourceError("岗位页面缺少足够的职位内容")
        return RawJob(
            source="public_job_page",
            source_job_id=hashlib.sha256(url.encode()).hexdigest()[:20],
            title=title,
            company=company,
            city=city,
            url=url,
            raw_text=raw_text,
            metadata={"structured": bool(posting), "schema": "JobPosting" if posting else "html"},
        )

    def load_url(self, url: str) -> RawJob:
        if not self.supports_url(url):
            raise SourceError("该 URL 不属于通用公开岗位网页")
        self.requests += 1
        try:
            if not self._robots_allows(url):
                raise SourceError("目标站点 robots.txt 不允许读取该岗位路径")
            body, final_url, content_type = self._fetch(url)
            job = self._parse(final_url, body, content_type)
        except SourceError as exc:
            self.failures += 1
            self.last_error = str(exc)
            raise
        self.successes += 1
        return job

    def _robots_allows(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        try:
            body, _, _ = self._fetch(robots_url)
        except SourceError:
            return True  # 站点未提供或暂时无法读取 robots.txt，不把它误判为显式禁止
        applies = False
        disallowed: list[str] = []
        for raw in body.decode("utf-8", "replace").splitlines():
            line = raw.split("#", 1)[0].strip()
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                applies = value == "*"
            elif applies and key == "disallow" and value:
                disallowed.append(value)
        return not any(parsed.path.startswith(path) for path in disallowed)

    def search(self, keyword: str, *, city: str | None = None, limit: int = 30) -> list[RawJob]:
        return []

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
            "policy": "user-provided HTTPS URL; public-IP validation; JobPosting JSON-LD preferred",
        }
