"""采集层：可插拔的岗位数据来源。

**这一层的存在本身就是一条架构决策**（见 PLAN.md ADR #2）：
招聘站点随时可能改版、加验证码、封 IP，合规风险也不可控。
把采集收敛到统一接口后面，任何单一来源失效都不会影响系统的分析能力。

契约：只负责「拿到原始 JD 文本」，不做结构化、不做统计。
"""

from .arbeitnow import ArbeitnowSource
from .base import JobSource, RawJob, SourceError, build_raw_text
from .brave import BraveJobSearchSource
from .greenhouse import GreenhouseJobSource
from .jobicy import JobicySource
from .manual import ManualPasteSource
from .ncss import NcssSource
from .nowcoder import NowcoderSource
from .public_page import PublicJobPageSource
from .sample import SampleSource
from .shixiseng import ShixisengSource

__all__ = [
    "JobSource",
    "ArbeitnowSource",
    "RawJob",
    "SourceError",
    "BraveJobSearchSource",
    "GreenhouseJobSource",
    "JobicySource",
    "ManualPasteSource",
    "NcssSource",
    "NowcoderSource",
    "PublicJobPageSource",
    "SampleSource",
    "ShixisengSource",
    "build_raw_text",
    "build_sources",
]


def build_sources(settings) -> list[JobSource]:
    """按配置组装可用的采集源。

    真实站点采集默认关闭（JOBRADAR_ENABLE_LIVE_SOURCES=0）：
    在拿到合规结论之前，不把它作为默认路径。
    """
    sources: list[JobSource] = []
    if settings.enable_sample_source:
        sources.append(SampleSource(settings.sample_dir))
    if settings.enable_live_sources:
        # 中国大陆公开源优先，避免海外源先耗尽本次在线预算。
        if settings.enable_ncss_source:
            sources.append(
                NcssSource(settings.live_cache_dir, timeout=settings.live_source_timeout)
            )
        if settings.enable_shixiseng_source:
            sources.append(
                ShixisengSource(settings.live_cache_dir, timeout=settings.live_source_timeout)
            )
        sources.append(
            NowcoderSource(
                settings.live_cache_dir,
                timeout=settings.live_source_timeout,
                min_interval=settings.live_source_interval,
                scan_limit=settings.nowcoder_scan_limit,
                search_budget=settings.live_source_budget,
            )
        )
        if settings.brave_search_api_key:
            sources.append(
                BraveJobSearchSource(
                    settings.brave_search_api_key, timeout=settings.live_source_timeout
                )
            )
        if settings.enable_jobicy_source:
            sources.append(
                JobicySource(
                    settings.live_cache_dir,
                    timeout=settings.live_source_timeout,
                )
            )
        if settings.enable_arbeitnow_source:
            sources.append(
                ArbeitnowSource(
                    settings.live_cache_dir,
                    timeout=settings.live_source_timeout,
                    pages=settings.arbeitnow_pages,
                )
            )
        if settings.greenhouse_boards:
            sources.append(
                GreenhouseJobSource(
                    settings.greenhouse_boards,
                    settings.live_cache_dir,
                    timeout=settings.live_source_timeout,
                )
            )
        sources.append(PublicJobPageSource(timeout=settings.live_source_timeout))
    return sources
