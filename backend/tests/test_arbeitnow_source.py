from __future__ import annotations

import json

from app.sources.arbeitnow import ArbeitnowSource


def payload() -> bytes:
    return json.dumps(
        {
            "data": [
                {
                    "slug": "marketing-video-artist-1",
                    "company_name": "Example Studio",
                    "title": "Marketing Video Artist",
                    "description": "Create campaign videos, edit footage, and design motion graphics. "
                    * 3,
                    "remote": False,
                    "url": "https://www.arbeitnow.com/jobs/marketing-video-artist-1",
                    "tags": ["Video", "Marketing"],
                    "job_types": ["full_time"],
                    "location": "Paris",
                    "created_at": 1,
                },
                {
                    "slug": "backend-1",
                    "company_name": "Example",
                    "title": "Backend Engineer",
                    "description": "Build backend services. " * 10,
                    "url": "https://www.arbeitnow.com/jobs/backend-1",
                    "location": "Berlin",
                },
            ]
        }
    ).encode()


def test_arbeitnow_expands_video_editor_to_related_real_title(tmp_path) -> None:
    requested: list[str] = []

    def opener(url: str) -> bytes:
        requested.append(url)
        return payload()

    source = ArbeitnowSource(tmp_path, pages=2, opener=opener)
    jobs = source.search("Video Editor", limit=5)

    assert [job.title for job in jobs] == ["Marketing Video Artist"]
    assert jobs[0].url == "https://www.arbeitnow.com/jobs/marketing-video-artist-1"
    assert jobs[0].metadata["source_attribution"] == "Arbeitnow"
    assert requested == [
        "https://www.arbeitnow.com/api/job-board-api?page=1",
        "https://www.arbeitnow.com/api/job-board-api?page=2",
    ]


def test_arbeitnow_reuses_catalog_cache(tmp_path) -> None:
    assert ArbeitnowSource(tmp_path, opener=lambda _url: payload()).search("Video Editor")
    offline = ArbeitnowSource(
        tmp_path,
        opener=lambda _url: (_ for _ in ()).throw(AssertionError("应读取缓存")),
    )
    assert offline.search("Video Editor")
    assert offline.cache_hits == 1
