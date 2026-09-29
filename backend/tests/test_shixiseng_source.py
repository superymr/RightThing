from __future__ import annotations

from app.sources.shixiseng import ShixisengSource


DETAIL = """
<html><body>
<div class="new_job_name"><span>视频剪辑实习生</span></div>
<div class="job_msg"><span title="深圳" class="job_position">深圳</span></div>
<div class="job_detail">岗位职责：负责短视频剪辑、字幕、调色和包装，配合策划完成内容制作。
任职要求：熟练使用 Premiere Pro、After Effects 和剪映，有作品集，沟通协作能力良好。</div>
<div class="job_city"><span class="com_position">广东省/深圳市/南山区</span></div>
<div class="com_intro"><a class="com-name">示例科技</a></div>
</body></html>
""".encode()


def test_shixiseng_discovers_and_parses_public_jobs(tmp_path) -> None:
    requested: list[str] = []

    def opener(url: str) -> bytes:
        requested.append(url)
        if "/interns?" in url:
            return b'<a href="https://www.shixiseng.com/intern/inn_demo123?pcm=pc_SearchList">job</a>'
        return DETAIL

    source = ShixisengSource(tmp_path, opener=opener)
    jobs = source.search("视频剪辑", limit=3)

    assert len(jobs) == 1
    assert jobs[0].title == "视频剪辑实习生"
    assert jobs[0].company == "示例科技"
    assert jobs[0].city == "深圳"
    assert jobs[0].url == "https://www.shixiseng.com/intern/inn_demo123"
    assert "Premiere Pro" in jobs[0].raw_text
    assert len(requested) == 2


def test_shixiseng_reuses_detail_cache(tmp_path) -> None:
    listing = b'<a href="/intern/inn_demo123">job</a>'
    warm = ShixisengSource(tmp_path, opener=lambda url: listing if "/interns?" in url else DETAIL)
    assert warm.search("剪辑")

    offline = ShixisengSource(
        tmp_path,
        opener=lambda url: listing
        if "/interns?" in url
        else (_ for _ in ()).throw(AssertionError("详情应读取缓存")),
    )
    assert offline.search("剪辑")
    assert offline.cache_hits == 1


def test_shixiseng_skips_offline_jobs(tmp_path) -> None:
    listing = b'<a href="/intern/inn_offline1">job</a>'
    detail = DETAIL.replace(b"</body>", "<div>当前职位已下线</div></body>".encode())
    source = ShixisengSource(
        tmp_path, opener=lambda url: listing if "/interns?" in url else detail
    )
    assert source.search("剪辑") == []
