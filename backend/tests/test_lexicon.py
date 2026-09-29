"""词表匹配的边界安全测试。

这些用例保护的是最容易出错、也最难发现的一类 bug：
`C` 匹配到 `C++`、`SQL` 匹配到 `MySQL` —— 它们不会报错，只会悄悄污染统计结果。
"""

from __future__ import annotations

from app.analytics.lexicon import SkillLexicon
from app.config import DEFAULT_ALIAS_PATH


def lexicon() -> SkillLexicon:
    return SkillLexicon.load(DEFAULT_ALIAS_PATH)


def names(text: str) -> set[str]:
    return {match.canonical for match in lexicon().find_in_text(text)}


class TestBoundarySafety:
    def test_c_does_not_match_c_plus_plus(self):
        assert "C" not in names("精通C++编程")
        assert "C++" in names("精通C++编程")

    def test_sql_does_not_match_mysql(self):
        assert "SQL" not in names("熟悉MySQL数据库")
        assert "MySQL" in names("熟悉MySQL数据库")

    def test_go_does_not_match_google_or_django(self):
        assert names("使用Google Analytics与Django框架") == set()

    def test_ros_does_not_match_ros2_alias_confusion(self):
        assert names("熟悉ROS2开发") == {"ROS"}

    def test_c_language_matches_c(self):
        assert "C" in names("熟悉C语言开发")

    def test_ethercat_is_not_can_bus(self):
        """EtherCAT 与 CAN 是两种不同的工业总线，不能混为一谈。"""
        assert names("了解EtherCAT总线通信") == {"EtherCAT"}
        assert names("熟悉CAN总线通信") == {"CAN总线"}

    def test_microcontroller_is_not_stm32(self):
        """单片机是统称，STM32 只是其中一款。"""
        assert "STM32" not in names("熟悉单片机移植")
        assert "单片机" in names("熟悉单片机移植")


class TestMatching:
    def test_chinese_alias_with_suffix(self):
        assert "Linux" in names("熟悉Linux开发环境")

    def test_multiple_skills_in_one_sentence(self):
        found = names("熟练掌握Python与SQL，熟悉Linux环境")
        assert {"Python", "SQL", "Linux"} <= found

    def test_each_skill_reported_once(self):
        found = [m.canonical for m in lexicon().find_in_text("Python python PYTHON")]
        assert found.count("Python") == 1

    def test_overlapping_aliases_prefer_longest(self):
        # "机器学习" 与 "学习能力" 是两个不同的技能，不应互相吞掉
        found = names("具备机器学习基础与较强的学习能力")
        assert "机器学习" in found
        assert "学习能力" in found

    def test_empty_text(self):
        assert lexicon().find_in_text("") == []
