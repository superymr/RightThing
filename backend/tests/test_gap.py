"""技能缺口分析测试 —— 项目最终输出的正确性保证。"""

from __future__ import annotations

from app.analytics.aggregator import aggregate
from app.analytics.gap import compute_gap
from app.llm.schemas import JDProfile, SkillItem


def build(n_jobs: int, skill: str, *, required_every: int = 1):
    """构造 n_jobs 条 JD，每 required_every 条出现一次该技能（否则记为加分项）。"""
    profiles = []
    for i in range(n_jobs):
        required = i % required_every == 0
        profiles.append(
            (
                f"j{i}",
                JDProfile(hard_skills=[SkillItem(name=skill, required=required)]),
            )
        )
    return profiles


class TestTiers:
    def test_high_coverage_required_skill_is_must_learn(self):
        result = aggregate(build(10, "SQL"), direction="x")
        gap = compute_gap([], result)
        assert [i.stat.canonical for i in gap.must_learn] == ["SQL"]

    def test_low_coverage_skill_is_nice_to_have(self):
        profiles = [
            ("j1", JDProfile(hard_skills=[SkillItem(name="Kubernetes", required=False)])),
            *[(f"j{i}", JDProfile(hard_skills=[SkillItem(name="SQL")])) for i in range(2, 11)],
        ]
        result = aggregate(profiles, direction="x")
        gap = compute_gap(["SQL"], result)
        assert [i.stat.canonical for i in gap.nice_to_have] == ["Kubernetes"]

    def test_middle_skill_is_should_learn(self):
        # 3/9 覆盖、全部为硬性要求 → 过 SHOULD 线（0.20）但未过 MUST 线（0.40）
        profiles = [
            *[(f"a{i}", JDProfile(hard_skills=[SkillItem(name="Hive")])) for i in range(3)],
            *[(f"b{i}", JDProfile(hard_skills=[SkillItem(name="SQL")])) for i in range(6)],
        ]
        result = aggregate(profiles, direction="x")
        gap = compute_gap(["SQL"], result)
        assert [i.stat.canonical for i in gap.should_learn] == ["Hive"]

    def test_single_mention_never_reaches_advice_tiers(self):
        """只被 1 个岗位提到、但在那个岗位里是硬性要求的技能，必须落到加分项。

        没有这道闸门，真模型的细粒度抽取会让「建议学」从十几项膨胀到六七十项 ——
        清单失去指导意义，用户看到的就是一堆噪音。
        """
        profiles = [
            ("j1", JDProfile(hard_skills=[SkillItem(name="TensorRT", required=True)])),
            *[
                (f"j{i}", JDProfile(hard_skills=[SkillItem(name="SQL", required=True)]))
                for i in range(2, 13)
            ],
        ]
        result = aggregate(profiles, direction="x")
        gap = compute_gap(["SQL"], result)
        assert [i.stat.canonical for i in gap.nice_to_have] == ["TensorRT"]
        assert gap.should_learn == []
        assert gap.must_learn == []


class TestSetOperations:
    def test_have_is_intersection(self):
        result = aggregate(build(10, "SQL"), direction="x")
        gap = compute_gap(["SQL", "Python"], result)
        assert [s.canonical for s in gap.have] == ["SQL"]

    def test_marginal_is_my_skills_minus_market(self):
        result = aggregate(build(10, "SQL"), direction="x")
        gap = compute_gap(["SQL", "火星车驾驶"], result)
        assert gap.marginal == ["火星车驾驶"]

    def test_case_insensitive_matching(self):
        result = aggregate(build(10, "SQL"), direction="x")
        gap = compute_gap(["sql"], result)
        assert len(gap.have) == 1

    def test_no_overlap_means_zero_coverage(self):
        result = aggregate(build(10, "SQL"), direction="x")
        gap = compute_gap(["Rust"], result)
        assert gap.coverage_score == 0.0
        assert gap.marginal == ["Rust"]

    def test_full_coverage(self):
        result = aggregate(build(10, "SQL"), direction="x")
        gap = compute_gap(["SQL"], result)
        assert gap.coverage_score == 1.0


class TestOrdering:
    def test_missing_sorted_by_tier_then_weight(self):
        profiles = []
        for i in range(10):
            profiles.append(
                (
                    f"j{i}",
                    JDProfile(
                        hard_skills=[
                            SkillItem(name="SQL", required=True),
                            *([SkillItem(name="Spark", required=True)] if i < 5 else []),
                            *([SkillItem(name="ClickHouse", required=False)] if i == 0 else []),
                        ],
                    ),
                )
            )
        result = aggregate(profiles, direction="x")
        gap = compute_gap([], result)
        tiers = [item.tier for item in gap.missing]
        assert tiers == sorted(tiers, key=lambda t: {"must": 0, "should": 1, "nice": 2}[t])
