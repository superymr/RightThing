"""Mock Provider（规则抽取引擎）测试。

它同时承担两个角色，所以值得单独测：
1. 无 API Key 时的默认抽取后端 —— 新人第一次运行看到的就是它的结果；
2. 单元测试的确定性基线 —— 真模型会漂移，规则引擎不会。

最关键的用例是 `test_evidence_is_substring_of_original`：
evidence 必须是原文片段，这是整个产品「可回溯、抗幻觉」承诺的技术基础。
"""

from __future__ import annotations

import pytest

from app.llm.base import LLMError
from app.llm.mock_provider import MockProvider
from app.llm.prompts import DIRECTION_USER_TEMPLATE, JD_EXTRACT_USER_TEMPLATE
from app.llm.schemas import Direction, JDProfile

JD_TEXT = """岗位名称：数据分析师
公司：某公司
工作地点：北京

岗位职责：
1. 负责业务数据的监控与归因分析，输出业务建议
2. 负责指标体系的设计与维护

任职要求：
1. 本科及以上学历，统计学、数学、计算机相关专业
2. 3年以上数据分析相关工作经验
3. 熟练掌握Python与SQL，具备良好的数据处理能力
4. 熟悉Linux开发环境，掌握Git进行协作
5. 熟悉数据可视化工具，能够输出分析结论
6. 具备良好的沟通能力

加分项：
1. 熟悉Docker与Kubernetes者优先
2. 有A/B测试经验者优先
"""


@pytest.fixture()
def provider() -> MockProvider:
    return MockProvider()


def extract(provider: MockProvider) -> tuple[JDProfile, str]:
    user = JD_EXTRACT_USER_TEMPLATE.format(
        job_title="数据分析师", company="某公司", jd_text=JD_TEXT
    )
    response = provider.complete_json(system="", user=user, schema_name="jd_profile")
    return JDProfile.from_dict(response.data), response.raw_text


class TestSkillExtraction:
    def test_languages_extracted(self, provider):
        profile, _ = extract(provider)
        names = {item.name for item in profile.programming_languages}
        assert {"Python", "SQL"} <= names

    def test_hard_skills_extracted(self, provider):
        profile, _ = extract(provider)
        names = {item.name for item in profile.hard_skills}
        assert {"Linux", "Git", "Docker", "Kubernetes", "A/B测试"} <= names

    def test_soft_skills_extracted(self, provider):
        profile, _ = extract(provider)
        assert {item.name for item in profile.soft_skills} == {"沟通能力"}

    def test_mysql_like_false_positive_absent(self, provider):
        """JD 里没有 MySQL，就不该抽出来。"""
        profile, _ = extract(provider)
        assert "MySQL" not in {item.name for item in profile.all_skills()}


class TestRequiredFlag:
    def test_requirements_section_is_required(self, provider):
        profile, _ = extract(provider)
        python = next(i for i in profile.programming_languages if i.name == "Python")
        assert python.required is True

    def test_preferred_section_is_not_required(self, provider):
        profile, _ = extract(provider)
        docker = next(i for i in profile.hard_skills if i.name == "Docker")
        assert docker.required is False

    def test_marker_word_overrides_section(self, provider):
        """「有A/B测试经验者优先」即使写在加分项之外，也应判为加分。"""
        text = JD_TEXT.replace("2. 有A/B测试经验者优先", "")
        user = JD_EXTRACT_USER_TEMPLATE.format(
            job_title="x", company="y", jd_text=text + "\n任职要求：\n7. 有A/B测试经验者优先\n"
        )
        data = provider.complete_json(system="", user=user, schema_name="jd_profile").data
        profile = JDProfile.from_dict(data)
        ab = next(i for i in profile.hard_skills if i.name == "A/B测试")
        assert ab.required is False


class TestOtherFields:
    def test_education(self, provider):
        profile, _ = extract(provider)
        assert profile.education == "本科及以上"

    def test_major(self, provider):
        profile, _ = extract(provider)
        assert {"统计学", "数学", "计算机"} <= set(profile.major)

    def test_major_window_does_not_cross_lines(self, provider):
        """回归用例：上一行的职责文案不能污染下一行的专业要求。

        「负责资源成本控制」+「计算机相关专业」曾经被抽成「控制」专业。
        """
        text = (
            "岗位职责：\n"
            "1. 负责性能优化与资源成本控制\n"
            "任职要求：\n"
            "1. 本科及以上学历，计算机、软件工程相关专业\n"
        )
        user = JD_EXTRACT_USER_TEMPLATE.format(job_title="x", company="y", jd_text=text)
        data = provider.complete_json(system="", user=user, schema_name="jd_profile").data
        profile = JDProfile.from_dict(data)
        assert set(profile.major) == {"计算机", "软件工程"}

    def test_experience(self, provider):
        profile, _ = extract(provider)
        assert profile.experience_years == "3年以上"

    def test_job_title_from_context_not_text(self, provider):
        profile, _ = extract(provider)
        assert profile.job_title == "数据分析师"

    def test_responsibilities_extracted(self, provider):
        profile, _ = extract(provider)
        assert len(profile.responsibilities) == 2
        assert "归因分析" in profile.responsibilities[0]

    def test_preferred_qualifications_collected(self, provider):
        profile, _ = extract(provider)
        assert any("A/B测试" in q for q in profile.preferred_qualifications)


class TestEvidence:
    def test_evidence_is_substring_of_original(self, provider):
        """★ 核心不变量：每条技能的 evidence 必须在原文里逐字出现。"""
        profile, _ = extract(provider)
        for item in profile.all_skills():
            assert item.evidence, f"{item.name} 缺少 evidence"
            assert item.evidence in JD_TEXT, f"{item.name} 的 evidence 不在原文中：{item.evidence!r}"


class TestDirectionRecommendation:
    def test_recommends_matching_direction(self, provider):
        user = DIRECTION_USER_TEMPLATE.format(skills="Python、SQL、数据可视化、统计分析")
        data = provider.complete_json(
            system="", user=user, schema_name="direction_recommendation"
        ).data
        directions = Direction.list_from(data)
        assert directions[0].title == "数据分析师"
        assert directions[0].match_score > 0.5
        assert directions[0].keywords

    def test_robot_skills_recommend_robot_direction(self, provider):
        user = DIRECTION_USER_TEMPLATE.format(skills="ROS、C++、SLAM、Linux")
        data = provider.complete_json(
            system="", user=user, schema_name="direction_recommendation"
        ).data
        assert Direction.list_from(data)[0].title == "机器人算法工程师"

    def test_unknown_skills_still_produce_a_searchable_direction(self, provider):
        """词表没覆盖时也不能空手而归 —— 否则用户会以为程序坏了。"""
        user = DIRECTION_USER_TEMPLATE.format(skills="火星车驾驶、星际导航")
        data = provider.complete_json(
            system="", user=user, schema_name="direction_recommendation"
        ).data
        directions = Direction.list_from(data)
        assert directions and directions[0].keywords

    def test_unknown_schema_raises(self, provider):
        with pytest.raises(LLMError):
            provider.complete_json(system="", user="", schema_name="nope")


class TestDeterminism:
    def test_same_input_same_output(self, provider):
        first, _ = extract(provider)
        second, _ = extract(provider)
        assert first.to_dict() == second.to_dict()
