from __future__ import annotations

import json

from app.sources.ncss import NcssSource


def listing() -> bytes:
    return json.dumps(
        {
            "flag": True,
            "data": {
                "list": [
                    {
                        "jobId": "demo123",
                        "jobName": "短视频剪辑师",
                        "recName": "示例传媒",
                        "areaCodeName": "上海",
                        "degreeName": "本科及以上",
                        "publishDate": 1790000000000,
                    }
                ]
            },
        },
        ensure_ascii=False,
    ).encode()


DETAIL = """
<html><body>
<li class="job-title basic-color">短视频剪辑师</li>
<div class="jobdetail-box"><div class="mainContent">岗位职责：负责短视频粗剪、精剪、字幕、调色和包装，按计划交付成片。
任职要求：熟练使用 Premiere Pro、After Effects、剪映，具备审美能力和良好的沟通协作能力。</div></div>
<span id="realCorpName">示例传媒</span>
<span id="companyNameMap">上海市浦东新区</span>
</body></html>
""".encode()


def test_ncss_reads_public_list_and_job_detail(tmp_path) -> None:
    requested: list[str] = []

    def opener(url: str) -> bytes:
        requested.append(url)
        return listing() if "jobslist/ajax" in url else DETAIL

    source = NcssSource(tmp_path, opener=opener)
    jobs = source.search("视频剪辑", limit=2)

    assert len(jobs) == 1
    assert jobs[0].title == "短视频剪辑师"
    assert jobs[0].company == "示例传媒"
    assert jobs[0].city == "上海"
    assert jobs[0].url.endswith("/student/jobs/demo123/detail.html")
    assert jobs[0].metadata["source_attribution"] == "国家大学生就业服务平台"
    assert len(requested) == 2


def test_ncss_reuses_detail_cache(tmp_path) -> None:
    warm = NcssSource(tmp_path, opener=lambda url: listing() if "jobslist/ajax" in url else DETAIL)
    assert warm.search("剪辑")

    offline = NcssSource(
        tmp_path,
        opener=lambda url: listing()
        if "jobslist/ajax" in url
        else (_ for _ in ()).throw(AssertionError("详情应读取缓存")),
    )
    assert offline.search("剪辑")
    assert offline.cache_hits == 1


def test_ncss_skips_offline_job(tmp_path) -> None:
    offline_detail = DETAIL.replace(b"</body>", "<div>职位已下线</div></body>".encode())
    source = NcssSource(
        tmp_path,
        opener=lambda url: listing() if "jobslist/ajax" in url else offline_detail,
    )
    assert source.search("剪辑") == []
