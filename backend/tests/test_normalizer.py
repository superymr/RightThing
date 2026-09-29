"""归一化测试。

核心不变量：**同一个概念的不同写法必须收敛到同一个规范名**。
否则 "python3" 与 "Python" 会被统计成两项，排行榜直接失真。
"""

from __future__ import annotations

import pytest

from app.analytics.lexicon import SkillLexicon
from app.analytics.normalizer import Normalizer, clean
from app.config import DEFAULT_ALIAS_PATH
from app.models.db import Database


@pytest.fixture()
def normalizer(tmp_path) -> Normalizer:
    lexicon = SkillLexicon.load(DEFAULT_ALIAS_PATH)
    db = Database(tmp_path / "test.db")
    db.init_schema()
    return Normalizer(lexicon, db)


class TestClean:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("熟练使用Python", "Python"),
            ("精通C++", "C++"),
            ("了解ROS", "ROS"),
            ("具备数据分析能力", "数据分析"),
            ("Python编程", "Python"),
            ("  机器学习  ", "机器学习"),
            ("、SQL；", "SQL"),
        ],
    )
    def test_strip_modifiers(self, raw, expected):
        assert clean(raw) == expected


class TestNormalize:
    def test_alias_converges_to_canonical(self, normalizer):
        assert normalizer.normalize_one("python3").canonical == "Python"
        assert normalizer.normalize_one("Python编程").canonical == "Python"
        assert normalizer.normalize_one("PYTHON").canonical == "Python"

    def test_ros_variants(self, normalizer):
        for variant in ("ROS", "ros2", "ROS1", "机器人操作系统"):
            assert normalizer.normalize_one(variant).canonical == "ROS"

    def test_category_is_attached(self, normalizer):
        assert normalizer.normalize_one("Python").category == "编程语言"
        assert normalizer.normalize_one("PyTorch").category == "深度学习框架"

    def test_unknown_skill_is_registered_not_dropped(self, normalizer):
        """没见过的技能绝不丢弃 —— 丢弃会让用户以为系统理解了他。"""
        result = normalizer.normalize_one("火星车驾驶")
        assert result.canonical == "火星车驾驶"
        assert result.known is False

    def test_learned_skill_is_remembered(self, normalizer):
        normalizer.normalize_one("火星车驾驶")
        assert normalizer.normalize_one("火星车驾驶").known is True

    def test_dedupe_keeps_first_occurrence(self, normalizer):
        result = normalizer.normalize_many(["python3", "Python", "python编程", "SQL"])
        assert [s.canonical for s in result] == ["Python", "SQL"]

    def test_learned_alias_persists_to_db(self, tmp_path):
        lexicon = SkillLexicon.load(DEFAULT_ALIAS_PATH)
        db = Database(tmp_path / "persist.db")
        db.init_schema()

        Normalizer(lexicon, db).normalize_one("量子计算调参")

        # 重新构造一个 Normalizer，模拟「下次运行」
        fresh = Normalizer(lexicon, db)
        assert fresh.normalize_one("量子计算调参").known is True


class TestNormalizeItemNames:
    """处理大模型自由文本的核心入口，mock 路径不会走到这里。"""

    def test_exact_match_still_works(self, normalizer):
        result = normalizer.normalize_item_names("Python3")
        assert [s.canonical for s in result] == ["Python"]

    def test_decorated_name_collapses_to_one(self, normalizer):
        """带修饰的短语应替换成规范名，而不是各自成为一项。"""
        assert [s.canonical for s in normalizer.normalize_item_names("PID控制算法")] == ["PID控制"]
        assert [s.canonical for s in normalizer.normalize_item_names("团队协作意识")] == ["团队协作"]
        assert [s.canonical for s in normalizer.normalize_item_names("Git版本管理")] == ["Git"]

    def test_compound_name_is_split_into_multiple(self, normalizer):
        """复合名本来就是多项要求，应拆开 —— 否则会变成一个从未见过的长尾技能。"""
        result = normalizer.normalize_item_names("嵌入式开发与单片机移植")
        assert {s.canonical for s in result} == {"嵌入式开发", "单片机"}

    def test_unknown_name_falls_back_to_learning(self, normalizer):
        result = normalizer.normalize_item_names("星际导航调参")
        assert [s.canonical for s in result] == ["星际导航调参"]
        assert result[0].known is False

    def test_empty_input(self, normalizer):
        assert normalizer.normalize_item_names("") == []
        assert normalizer.normalize_item_names("   ") == []

    def test_category_comes_from_lexicon(self, normalizer):
        result = normalizer.normalize_item_names("PID控制算法")
        assert result[0].category == "机器人/感知"
