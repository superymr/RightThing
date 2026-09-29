from __future__ import annotations

import json

import pytest

from app.sources import SourceError
from app.sources.public_page import PublicJobPageSource


def job_page() -> bytes:
    posting = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "世界模型研究工程师",
        "hiringOrganization": {"@type": "Organization", "name": "Example AI"},
        "jobLocation": {
            "@type": "Place",
            "address": {"addressLocality": "上海", "addressRegion": "上海"},
        },
        "description": "负责生成式世界模型的研究和工程落地。",
        "responsibilities": "构建视频预测与物理一致性模型。",
        "skills": "Python, PyTorch, Diffusion, Transformer",
        "qualifications": "计算机相关专业硕士优先。",
    }
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps(posting, ensure_ascii=False)
        + "</script></head><body>job</body></html>"
    ).encode()


def test_imports_schema_org_job_posting():
    source = PublicJobPageSource(
        fetcher=lambda url: (job_page(), url, "text/html; charset=utf-8")
    )
    job = source.load_url("https://careers.example.com/jobs/world-model")
    assert job.title == "世界模型研究工程师"
    assert job.company == "Example AI"
    assert job.city == "上海 上海"
    assert "Diffusion" in job.raw_text
    assert job.metadata["structured"] is True


@pytest.mark.parametrize(
    "url",
    ["http://careers.example.com/job/1", "https://127.0.0.1/job/1", "file:///etc/passwd"],
)
def test_rejects_unsafe_or_unsupported_urls(url):
    source = PublicJobPageSource(fetcher=lambda value: (job_page(), value, "text/html"))
    if url.startswith("https://127"):
        # injected fetchers bypass DNS by design, so exercise the production validator directly
        with pytest.raises(SourceError):
            source._validate_public(url)
    else:
        with pytest.raises(SourceError):
            source.load_url(url)


def test_respects_robots_disallow():
    def fetcher(url: str):
        if url.endswith("/robots.txt"):
            return b"User-agent: *\nDisallow: /private-jobs\n", url, "text/plain"
        return job_page(), url, "text/html"

    source = PublicJobPageSource(fetcher=fetcher)
    with pytest.raises(SourceError, match="robots.txt"):
        source.load_url("https://careers.example.com/private-jobs/42")
