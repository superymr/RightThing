"""技能缺口分析 —— 这个项目真正的价值出口。

排行本身只是「信息」，用户要的是「我该学什么」。缺口分析把
「市场要求」与「我已掌握」做集合运算，并按优先级分档：

    市场要求 R（按加权分排序）
    我的技能 M
    ├── R ∩ M  → 优势项      （简历上要突出写的）
    ├── R − M  → 学习清单    （必学 / 建议学 / 加分项 三档）
    └── M − R  → 边缘技能    （该方向用不上，可暂缓投入）

分档规则不是拍脑袋，而是两个可解释量的组合：
- `coverage`（多少岗位要它）—— 决定「值不值得学」；
- `required_ratio`（其中多少是硬性要求）—— 决定「不学行不行」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .aggregator import AggregateResult, SkillStat

# 分档阈值：集中在此，方便按真实数据校准
MUST_COVERAGE = 0.40
MUST_REQUIRED_RATIO = 0.60
SHOULD_COVERAGE = 0.20
SHOULD_REQUIRED_RATIO = 0.40

# 只有**一个**岗位提到的技能，无论在那个岗位里多硬性，都不足以构成建议：
# 那是噪音，不是市场信号。没有这道闸门，真模型抽取的细粒度会让
# 「建议学」从十几项膨胀到六七十项，清单直接失去指导意义。
MIN_JOBS = 2


@dataclass
class GapItem:
    stat: SkillStat
    tier: str  # must | should | nice

    @property
    def tier_label(self) -> str:
        return {"must": "必学", "should": "建议学", "nice": "加分项"}.get(self.tier, self.tier)

    def to_dict(self) -> dict:
        return {"tier": self.tier, "tier_label": self.tier_label, **self.stat.to_dict()}


@dataclass
class GapReport:
    have: list[SkillStat] = field(default_factory=list)
    missing: list[GapItem] = field(default_factory=list)
    marginal: list[str] = field(default_factory=list)
    market_weight: float = 0.0
    covered_weight: float = 0.0

    @property
    def coverage_score(self) -> float:
        """加权覆盖率：你的技能覆盖了市场多少「要求权重」。

        比单纯数技能个数更贴近现实 —— 覆盖一个高覆盖率的必学技能，
        和覆盖一个冷门加分项，价值完全不同。
        """
        if self.market_weight <= 0:
            return 0.0
        return round(self.covered_weight / self.market_weight, 3)

    @property
    def must_learn(self) -> list[GapItem]:
        return [item for item in self.missing if item.tier == "must"]

    @property
    def should_learn(self) -> list[GapItem]:
        return [item for item in self.missing if item.tier == "should"]

    @property
    def nice_to_have(self) -> list[GapItem]:
        return [item for item in self.missing if item.tier == "nice"]

    def to_dict(self) -> dict:
        return {
            "coverage_score": self.coverage_score,
            "market_weight": round(self.market_weight, 2),
            "covered_weight": round(self.covered_weight, 2),
            "have": [s.to_dict() for s in self.have],
            "must_learn": [i.to_dict() for i in self.must_learn],
            "should_learn": [i.to_dict() for i in self.should_learn],
            "nice_to_have": [i.to_dict() for i in self.nice_to_have],
            "marginal": self.marginal,
        }


def compute_gap(my_skills: list[str], result: AggregateResult) -> GapReport:
    """my_skills 需为归一化后的规范名。"""
    owned = {s.strip().lower() for s in my_skills if s and s.strip()}
    market = result.all_skills
    market_keys = {stat.canonical.lower() for stat in market}

    report = GapReport()
    report.market_weight = sum(stat.weighted_score for stat in market)

    for stat in market:
        if stat.canonical.lower() in owned:
            report.have.append(stat)
            report.covered_weight += stat.weighted_score
        else:
            report.missing.append(GapItem(stat=stat, tier=_tier_of(stat)))

    # 排序：必学 → 建议学 → 加分项，同档内按加权分
    order = {"must": 0, "should": 1, "nice": 2}
    report.missing.sort(key=lambda i: (order[i.tier], -i.stat.weighted_score, i.stat.canonical))

    # 边缘技能：我有，但这个方向几乎不需要（保留用户输入原貌）
    report.marginal = sorted(s for s in my_skills if s.strip().lower() not in market_keys)
    return report


def _tier_of(stat: SkillStat) -> str:
    if stat.count < MIN_JOBS:
        return "nice"
    if stat.coverage >= MUST_COVERAGE and stat.required_ratio >= MUST_REQUIRED_RATIO:
        return "must"
    if stat.coverage >= SHOULD_COVERAGE or stat.required_ratio >= SHOULD_REQUIRED_RATIO:
        return "should"
    return "nice"
