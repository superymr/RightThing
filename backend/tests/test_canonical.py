"""自由文本 → 规范值 的收敛测试。

这一层是 mock 路径测不到的死角：mock 返回的名字来自词表，天生规范。
真模型返回 "硕士及以上学历"、"3年以上SLAM相关研发经验"、"机械电子工程"，
不收敛就会让同一个概念在统计里占三行。
"""

from __future__ import annotations

import pytest

from app.analytics.canonical import (
    canonical_education,
    canonical_experience,
    canonical_majors,
    canonical_seniority,
    extract_majors,
)


class TestEducation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("本科及以上学历", "本科及以上"),
            ("本科及以上", "本科及以上"),
            ("硕士及以上学历", "硕士及以上"),
            ("硕士", "硕士"),
            ("博士", "博士"),
            ("大专学历", "大专"),
            ("学历不限", "学历不限"),
            ("", ""),
        ],
    )
    def test_canonical(self, raw, expected):
        assert canonical_education(raw) == expected

    def test_different_phrasings_converge(self):
        """同一个概念的不同说法必须收敛到同一个值，否则统计里会出现三行。"""
        variants = ["本科及以上", "本科及以上学历", "本科以上学历"]
        assert len({canonical_education(v) for v in variants}) == 1


class TestExperience:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("3年以上", "3年以上"),
            ("3年以上SLAM相关研发经验", "3年以上"),
            ("2年以上ROS开发经验", "2年以上"),
            ("3-5年", "3-5年"),
            ("1~3年工作经验", "1-3年"),
            ("应届生可", "应届"),
        ],
    )
    def test_canonical(self, raw, expected):
        assert canonical_experience(raw) == expected

    def test_different_phrasings_converge(self):
        variants = ["3年以上", "3年以上经验", "3年以上相关研发经验"]
        assert len({canonical_experience(v) for v in variants}) == 1

    def test_empty(self):
        assert canonical_experience("") == ""


class TestMajors:
    def test_unknown_major_is_kept_not_dropped(self):
        assert canonical_majors(["火星车工程"]) == ["火星车工程"]

    def test_maps_to_whitelist(self):
        assert canonical_majors(["机械电子工程"]) == ["机械"]
        assert canonical_majors(["控制科学与工程"]) == ["控制"]
        assert canonical_majors(["模式识别与智能系统"]) == ["模式识别"]

    def test_dedupes_after_mapping(self):
        assert canonical_majors(["机械工程", "机械"]) == ["机械工程"]

    def test_empty_entries_ignored(self):
        assert canonical_majors(["", "  ", "数学"]) == ["数学"]


class TestExtractMajors:
    def test_chinese_enumeration(self):
        """「统计学、数学、计算机相关专业」里只有最后一个词与「专业」相邻。"""
        text = "本科及以上学历，统计学、数学、计算机相关专业"
        assert set(extract_majors(text)) == {"统计学", "数学", "计算机"}

    def test_window_does_not_cross_lines(self):
        """回归用例：上一行的职责文案不能污染下一行的专业要求。"""
        text = (
            "岗位职责：\n"
            "1. 负责性能优化与资源成本控制\n"
            "任职要求：\n"
            "1. 本科及以上学历，计算机、软件工程相关专业\n"
        )
        assert set(extract_majors(text)) == {"计算机", "软件工程"}

    def test_prefers_longest_major_name(self):
        text = "控制工程、机械工程相关专业"
        found = extract_majors(text)
        assert "控制工程" in found
        assert "机械工程" in found

    def test_no_major_found(self):
        assert extract_majors("负责数据处理工作") == []


class TestSeniority:
    @pytest.mark.parametrize(
        "text,experience,expected",
        [
            ("应届毕业生优先", "", "应届"),
            ("", "1年以上", "初级"),
            ("", "2年以上", "中级"),
            ("", "5年以上", "高级"),
            ("", "8年以上", "专家"),
            ("", "", ""),
        ],
    )
    def test_canonical(self, text, experience, expected):
        assert canonical_seniority(text, experience) == expected
