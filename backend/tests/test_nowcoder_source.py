from __future__ import annotations

import json
import time

from app.config import Settings
from app.sources import NowcoderSource, RawJob, build_sources


def detail_page(
    job_id: int = 456905,
    title: str = "世界模型算法工程师",
    city: str = "杭州",
) -> bytes:
    detail = {
        "id": job_id,
        "status": 0,
        "updateTime": 123456,
        "jobName": title,
        "jobCity": city,
        "ext": json.dumps(
            {
                "infos": "负责世界模型、视频预测与仿真系统研发。",
                "requirements": "熟悉 PyTorch、Diffusion 与分布式训练。",
            },
            ensure_ascii=False,
        ),
        "recommendInternCompany": {"companyName": "示例科技"},
    }
    state = {"store": {"jobDetail": {"detail": detail}}}
    return (
        "<html><script>window.__INITIAL_STATE__="
        + json.dumps(state, ensure_ascii=False)
        + ";</script></html>"
    ).encode()


def test_nowcoder_uses_public_sitemap_and_parses_detail(tmp_path):
    requested: list[str] = []

    def opener(url: str) -> bytes:
        requested.append(url)
        if url.endswith("robots.txt"):
            return b"User-agent: *\nDisallow: /search\n"
        if url.endswith("sitemap1.xml"):
            return (
                "<urlset><url><loc>https://www.nowcoder.com/jobs/detail/456905?urlSource=sitemap"
                "</loc></url></urlset>"
            ).encode()
        return detail_page()

    source = NowcoderSource(tmp_path / "cache", opener=opener, scan_limit=5)
    jobs = source.search("世界模型算法工程师", limit=1)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "nowcoder"
    assert job.source_job_id == "456905"
    assert job.title == "世界模型算法工程师"
    assert job.company == "示例科技"
    assert job.city == "杭州"
    assert "Diffusion" in job.raw_text
    assert all("/search" not in url for url in requested)
    assert (tmp_path / "cache" / "nowcoder-jobs.json").is_file()


def test_cached_match_needs_no_network(tmp_path):
    cache_dir = tmp_path / "cache"

    def warm(url: str) -> bytes:
        if url.endswith("robots.txt"):
            return b"User-agent: *\nDisallow: /search\n"
        if url.endswith("sitemap1.xml"):
            return b"<urlset><url><loc>https://www.nowcoder.com/jobs/detail/1</loc></url></urlset>"
        return detail_page(job_id=1)

    assert NowcoderSource(cache_dir, opener=warm).search("世界模型", limit=1)

    def offline(_url: str) -> bytes:
        raise AssertionError("缓存命中不应访问网络")

    jobs = NowcoderSource(cache_dir, opener=offline).search("世界模型", limit=1)
    assert [job.source_job_id for job in jobs] == ["1"]


def test_video_editing_direction_matches_related_real_job_titles() -> None:
    job = RawJob(
        source="nowcoder",
        source_job_id="469770",
        title="27届秋招-AI视频设计师",
        company="完美世界",
        city="广州",
        url="https://www.nowcoder.com/jobs/detail/469770",
        raw_text="负责游戏宣传视频的设计与后期制作。",
    )

    assert NowcoderSource._score(job, "短视频剪辑师") > 0
    assert NowcoderSource._score(job, "视频包装/动效设计") > 0


def test_single_generic_video_mention_in_body_does_not_match_editing_role() -> None:
    job = RawJob(
        source="nowcoder",
        source_job_id="unrelated",
        title="机电工程师",
        raw_text="参与设备维护，面试流程包含视频面试。",
    )

    assert NowcoderSource._score(job, "短视频剪辑师") == 0

    ecommerce_support = RawJob(
        source="nowcoder",
        source_job_id="support",
        title="电商客服",
        raw_text="负责电商平台售后服务与客户沟通。",
    )
    assert NowcoderSource._score(ecommerce_support, "电商短视频剪辑") == 0


def test_expired_deadline_still_returns_matching_cached_jobs(tmp_path) -> None:
    cache_dir = tmp_path / "cache"

    def warm(url: str) -> bytes:
        if url.endswith("robots.txt"):
            return b"User-agent: *\nDisallow: /search\n"
        if url.endswith("sitemap1.xml"):
            return b"<urlset><url><loc>https://www.nowcoder.com/jobs/detail/2</loc></url></urlset>"
        return detail_page(job_id=2, title="AI视频设计师")

    assert NowcoderSource(cache_dir, opener=warm).search("视频", limit=1)

    def offline(_url: str) -> bytes:
        raise AssertionError("过期在线预算仍应先查询本地缓存")

    jobs = NowcoderSource(cache_dir, opener=offline).search_with_context(
        "短视频剪辑师", deadline=time.monotonic() - 1
    )
    assert [job.source_job_id for job in jobs] == ["2"]


def test_builder_only_enables_live_source_explicitly(tmp_path):
    disabled = build_sources(Settings(sample_dir=tmp_path, enable_live_sources=False))
    assert [source.name for source in disabled] == ["sample"]

    enabled = build_sources(
        Settings(sample_dir=tmp_path, enable_live_sources=True, live_cache_dir=tmp_path / "cache")
    )
    assert [source.name for source in enabled] == [
        "sample",
        "ncss",
        "shixiseng",
        "nowcoder",
        "jobicy",
        "arbeitnow",
        "greenhouse_official",
        "public_job_page",
    ]


def test_scan_honors_expired_deadline(tmp_path):
    requested: list[str] = []

    def opener(url: str) -> bytes:
        requested.append(url)
        if url.endswith("robots.txt"):
            return b"User-agent: *\nDisallow: /search\n"
        return b"<urlset><url><loc>https://www.nowcoder.com/jobs/detail/1</loc></url></urlset>"

    source = NowcoderSource(tmp_path / "cache", opener=opener)
    jobs = source.search_with_context("世界模型", deadline=time.monotonic() - 1)
    assert jobs == []
    assert not any("/jobs/detail/" in url for url in requested)


def test_direct_job_url_import(tmp_path):
    def opener(url: str) -> bytes:
        return detail_page(job_id=99, title="直接导入岗位")

    source = NowcoderSource(tmp_path / "cache", opener=opener)
    job = source.load_url("https://www.nowcoder.com/jobs/detail/99?from=user")
    assert job.source_job_id == "99"
    assert job.title == "直接导入岗位"
