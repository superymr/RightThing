from app.services.orchestrator import is_mainland_job
from app.sources import RawJob


def job(source: str, city: str, url: str = "https://example.com/job/1") -> RawJob:
    return RawJob(
        source=source,
        source_job_id="1",
        title="Video Editor",
        company="Example",
        city=city,
        url=url,
        raw_text=f"工作地点：{city}\n岗位描述：负责视频剪辑。",
    )


def test_mainland_market_accepts_mainland_locations() -> None:
    assert is_mainland_job(job("greenhouse_official", "Shanghai, China"))
    assert is_mainland_job(job("greenhouse_official", "深圳"))
    assert is_mainland_job(job("nowcoder", "北京"))


def test_mainland_market_rejects_overseas_remote_and_special_regions() -> None:
    assert not is_mainland_job(job("jobicy", "Worldwide"))
    assert not is_mainland_job(job("arbeitnow", "Paris, France"))
    assert not is_mainland_job(job("greenhouse_official", "Hong Kong, China"))
    assert not is_mainland_job(job("greenhouse_official", "Taipei, Taiwan"))


def test_known_chinese_recruitment_domains_are_accepted() -> None:
    assert is_mainland_job(
        job("brave_search", "", "https://www.zhipin.com/job_detail/example.html")
    )
