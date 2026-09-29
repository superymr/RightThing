"""分析层：归一化、聚合、排名、缺口计算。

本层是**纯函数区**：不碰网络、不碰 LLM、不碰 HTTP。
输入结构化数据，输出统计结论 —— 因此可以用单元测试完整覆盖。

这是 PLAN.md「LLM 只做抽取、代码做统计」这条红线的落点。
"""

from .aggregator import AggregateResult, aggregate
from .gap import GapReport, compute_gap
from .lexicon import SkillLexicon
from .normalizer import Normalizer

__all__ = [
    "AggregateResult",
    "GapReport",
    "Normalizer",
    "SkillLexicon",
    "aggregate",
    "compute_gap",
]
