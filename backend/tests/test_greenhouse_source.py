from __future__ import annotations

import json

from app.sources.greenhouse import GreenhouseJobSource


def test_greenhouse_searches_company_board_and_loads_real_detail(tmp_path) -> None:
    requested: list[str] = []

    def opener(url: str) -> bytes:
        requested.append(url)
        if url.endswith("/jobs"):
            return json.dumps(
                {
                    "jobs": [
                        {
                            "id": 7,
                            "title": "Senior Video Editor",
                            "location": {"name": "Remote"},
                            "absolute_url": "https://boards.greenhouse.io/studio/jobs/7",
                        },
                        {
                            "id": 8,
                            "title": "Backend Engineer",
                            "location": {"name": "Remote"},
                        },
                    ]
                }
            ).encode()
        return json.dumps(
            {
                "id": 7,
                "title": "Senior Video Editor",
                "location": {"name": "Remote"},
                "absolute_url": "https://boards.greenhouse.io/studio/jobs/7",
                "content": "<p>Edit campaign videos with Premiere Pro and After Effects.</p>" * 3,
                "updated_at": "2026-09-27T00:00:00Z",
            }
        ).encode()

    source = GreenhouseJobSource(("studio",), tmp_path, opener=opener)
    jobs = source.search("Video Editor", limit=5)

    assert [job.title for job in jobs] == ["Senior Video Editor"]
    assert jobs[0].source == "greenhouse_official"
    assert jobs[0].company == "studio"
    assert jobs[0].url == "https://boards.greenhouse.io/studio/jobs/7"
    assert requested == [
        "https://boards-api.greenhouse.io/v1/boards/studio/jobs",
        "https://boards-api.greenhouse.io/v1/boards/studio/jobs/7",
    ]


def test_greenhouse_skips_chinese_query_without_network(tmp_path) -> None:
    source = GreenhouseJobSource(
        ("studio",),
        tmp_path,
        opener=lambda _url: (_ for _ in ()).throw(AssertionError("不应访问网络")),
    )
    assert source.search("视频剪辑师") == []
