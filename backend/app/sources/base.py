"""采集源统一契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..utils.timeutil import now_iso


class SourceError(RuntimeError):
    """采集源不可用或返回了无法解析的数据。"""


@dataclass
class RawJob:
    """一份原始岗位数据。**只有原文，没有解析结果。**"""

    source: str
    source_job_id: str
    title: str
    raw_text: str
    company: str = ""
    city: str = ""
    url: str = ""
    direction: str = ""  # 来源方向（用于分组统计）
    metadata: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=now_iso)

    @property
    def content_hash(self) -> str:
        import hashlib

        return hashlib.sha256(self.raw_text.strip().encode("utf-8")).hexdigest()


def build_raw_text(
    *,
    title: str,
    company: str = "",
    city: str = "",
    responsibilities: list[str],
    requirements: list[str],
    extra_lines: list[str] | None = None,
) -> str:
    """把结构化样例拼成「像真实 JD 一样」的纯文本。

    刻意保留「岗位职责 / 任职要求」这类真实标题 ——
    这样规则抽取器与真实模型面对的是同一种输入形态，两边结果可直接对比。
    """
    lines: list[str] = [f"岗位名称：{title}"]
    if company:
        lines.append(f"公司：{company}")
    if city:
        lines.append(f"工作地点：{city}")

    lines.append("")
    lines.append("岗位职责：")
    lines.extend(f"{i}. {item}" for i, item in enumerate(responsibilities, 1))

    lines.append("")
    lines.append("任职要求：")
    lines.extend(f"{i}. {item}" for i, item in enumerate(requirements, 1))

    if extra_lines:
        lines.append("")
        lines.append("加分项：")
        lines.extend(f"{i}. {item}" for i, item in enumerate(extra_lines, 1))

    return "\n".join(lines)


@runtime_checkable
class JobSource(Protocol):
    """所有采集源必须实现的接口。"""

    name: str

    def search(self, keyword: str, *, city: str | None = None, limit: int = 30) -> list[RawJob]:
        """按关键词检索岗位。失败必须抛异常，不允许静默返回空列表。"""
        ...

    def fetch_detail(self, job: RawJob) -> RawJob:
        """补齐 JD 全文（列表页通常只有摘要）。"""
        ...
