from __future__ import annotations

import json
import urllib.parse

from app.sources.jobicy import JobicySource


def payload() -> bytes:
    return json.dumps(
        {
            "jobs": [
                {
                    "id": 42,
                    "url": "https://jobicy.com/jobs/video-editor-42",
                    "jobTitle": "Remote Video Editor",
                    "companyName": "Example Studio",
                    "jobGeo": "Worldwide",
                    "jobDescription": (
                        "<p>Edit long-form and short-form videos using Premiere Pro and "
                        "After Effects. Collaborate with producers and designers on campaigns.</p>"
                    ),
                    "pubDate": "2026-09-26",
                    "jobType": "full-time",
                }
            ]
        }
    ).encode()


def test_jobicy_returns_real_jobs_and_preserves_url(tmp_path) -> None:
    requested: list[str] = []

    def opener(url: str) -> bytes:
        requested.append(url)
        return payload()

    source = JobicySource(tmp_path, opener=opener)
    jobs = source.search("Video Editor", limit=5)

    assert len(jobs) == 1
    assert jobs[0].title == "Remote Video Editor"
    assert jobs[0].company == "Example Studio"
    assert jobs[0].url == "https://jobicy.com/jobs/video-editor-42"
    assert jobs[0].metadata["source_attribution"] == "Jobicy"
    assert urllib.parse.parse_qs(urllib.parse.urlparse(requested[0]).query)["tag"] == [
        "Video Editor"
    ]


def test_jobicy_skips_chinese_only_query_without_network(tmp_path) -> None:
    source = JobicySource(
        tmp_path,
        opener=lambda _url: (_ for _ in ()).throw(AssertionError("不应访问网络")),
    )
    assert source.search("视频剪辑师") == []


def test_jobicy_reuses_fresh_query_cache(tmp_path) -> None:
    warm = JobicySource(tmp_path, opener=lambda _url: payload())
    assert warm.search("Video Editor")

    offline = JobicySource(
        tmp_path,
        opener=lambda _url: (_ for _ in ()).throw(AssertionError("应读取缓存")),
    )
    assert offline.search("Video Editor")
    assert offline.cache_hits == 1
