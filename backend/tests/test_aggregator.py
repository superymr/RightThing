"""聚合统计测试。

这是全项目**最需要被测试覆盖**的模块：所有呈现在用户面前的数字都产自这里。
一旦算错，用户会据此做出「学什么」的决策。
"""

from __future__ import annotations

from app.analytics.aggregator import aggregate
from app.llm.schemas import JDProfile, SkillItem


def profile(*, languages=(), hard=(), preferred_hard=(), education="", majors=(), preferred=()):
    return JDProfile(
        job_title="测试岗位",
        education=education,
        major=list(majors),
        programming_languages=[SkillItem(name=n) for n in languages],
        hard_skills=[
            *[SkillItem(name=n, required=True) for n in hard],
            *[SkillItem(name=n, required=False) for n in preferred_hard],
        ],
        preferred_qualifications=list(preferred),
    )


class TestCounts:
    def test_count_and_coverage(self):
        profiles = [
            ("j1", profile(languages=["Python"])),
            ("j2", profile(languages=["Python"])),
            ("j3", profile(languages=["Java"])),
            ("j4", profile(languages=["Go"])),
        ]
        result = aggregate(profiles, direction="x")
        python = next(s for s in result.languages if s.canonical == "Python")

        assert result.total_jobs == 4
        assert python.count == 2
        assert python.coverage == 0.5

    def test_skill_counted_once_per_job(self):
        """一条 JD 里把 Python 写了三遍，也只能算一个岗位需要它。"""
        profiles = [
            (
                "j1",
                JDProfile(
                    programming_languages=[
                        SkillItem(name="Python"),
                        SkillItem(name="python"),
                        SkillItem(name="PYTHON"),
                    ]
                ),
            )
        ]
        result = aggregate(profiles, direction="x")
        assert result.languages[0].count == 1

    def test_required_wins_over_preferred_within_job(self):
        profiles = [
            (
                "j1",
                JDProfile(
                    hard_skills=[
                        SkillItem(name="Docker", required=False),
                        SkillItem(name="Docker", required=True),
                    ]
                ),
            )
        ]
        result = aggregate(profiles, direction="x")
        docker = result.hard_skills[0]
        assert docker.required_count == 1
        assert docker.preferred_count == 0


class TestWeighting:
    def test_weighted_score_uses_required_and_preferred(self):
        profiles = [
            ("j1", profile(languages=["Python"])),
            ("j2", profile(languages=["Python"])),
            ("j3", profile(preferred_hard=["Python"])),
        ]
        result = aggregate(profiles, direction="x")
        python = result.languages[0]
        assert python.required_count == 2
        assert python.preferred_count == 1
        assert python.weighted_score == 2.4  # 2×1.0 + 1×0.4

    def test_required_ratio(self):
        profiles = [
            ("j1", profile(languages=["Java"])),
            ("j2", profile(languages=["Java"])),
            ("j3", profile(preferred_hard=["Java"])),
            ("j4", profile(preferred_hard=["Java"])),
        ]
        result = aggregate(profiles, direction="x")
        assert result.languages[0].required_ratio == 0.5

    def test_ranking_sorted_by_weighted_score(self):
        profiles = [
            ("j1", profile(languages=["Python", "Java"])),
            ("j2", profile(languages=["Python"])),
        ]
        result = aggregate(profiles, direction="x")
        assert [s.canonical for s in result.languages] == ["Python", "Java"]


class TestBuckets:
    def test_categories_go_to_right_bucket(self):
        profiles = [
            (
                "j1",
                JDProfile(
                    programming_languages=[SkillItem(name="Python", category="编程语言")],
                    domain_knowledge=[SkillItem(name="SLAM", category="机器人/感知")],
                    soft_skills=[SkillItem(name="沟通能力", category="软技能")],
                    hard_skills=[SkillItem(name="Docker", category="工具与平台")],
                ),
            )
        ]
        result = aggregate(profiles, direction="x")
        assert [s.canonical for s in result.languages] == ["Python"]
        assert [s.canonical for s in result.domain_knowledge] == ["SLAM"]
        assert [s.canonical for s in result.soft_skills] == ["沟通能力"]
        assert [s.canonical for s in result.hard_skills] == ["Docker"]

    def test_all_skills_is_globally_sorted(self):
        profiles = [
            ("j1", profile(languages=["Python"])),
            ("j2", profile(languages=["Python"])),
            ("j3", profile(hard=["Docker"])),
        ]
        result = aggregate(profiles, direction="x")
        assert [s.canonical for s in result.all_skills] == ["Python", "Docker"]


class TestPreferences:
    def test_education_and_major_counts(self):
        profiles = [
            ("j1", profile(education="本科及以上", majors=["计算机"])),
            ("j2", profile(education="本科及以上", majors=["计算机", "数学"])),
            ("j3", profile(education="硕士及以上", majors=["数学"])),
        ]
        result = aggregate(profiles, direction="x")
        assert result.education[0].label == "本科及以上"
        assert result.education[0].count == 2
        assert result.education[0].coverage == round(2 / 3, 3)
        assert {m.label: m.count for m in result.majors} == {"计算机": 2, "数学": 2}

    def test_preferred_qualifications_merge_equivalent_wording(self):
        """措辞里只差标点/空格的同一条要求，必须合并计数。"""
        profiles = [
            ("j1", profile(preferred=["有机器人项目经验者优先"])),
            ("j2", profile(preferred=["有机器人项目经验者优先。"])),
            ("j3", profile(preferred=[" 有机器人项目经验者优先"])),
        ]
        result = aggregate(profiles, direction="x")
        assert len(result.preferred_qualifications) == 1
        assert result.preferred_qualifications[0].count == 3

    def test_empty_input(self):
        result = aggregate([], direction="x")
        assert result.total_jobs == 0
        assert result.all_skills == []
